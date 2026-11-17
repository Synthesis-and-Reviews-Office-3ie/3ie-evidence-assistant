#!/usr/bin/env python
"""SharePoint -> Cloudflare R2 ingest.

Reads a SharePoint document-library folder through the Microsoft Graph API and
streams the files into an R2 bucket. No file is routed through a user machine.

Auth
  Delegated (default): device-code sign-in with a public client. Requires the
  tenant to allow the app; no secret is stored.
  App-only: set GRAPH_CLIENT_SECRET to use client credentials. Requires an app
  registration with admin-consented Graph permissions (Sites.Selected or
  Sites.Read.All).
  The access token is refreshed on expiry, including mid-transfer on a 401.

Stages, runnable independently
  --r2-only   Verify R2 credentials and the destination bucket.
  --auth      Delegated device-code sign-in; caches tokens to .graph_token.json.
  --list      Resolve the folder and print a file inventory (no download).
  --probe     Copy the smallest file to R2 under the probe prefix, then verify it.
  --sync      Copy the folder to R2. Idempotent: skips keys already present.

Safety
  --sync defaults to a staging prefix (SP_KEY_PREFIX, default _staging/...). Writing
  into the live pipeline prefixes (input-pdfs/, rags/) requires an explicit --prefix
  plus --yes, unless --dry-run is used.

Config (env or .env): SP_HOST, SP_SITE_PATH, SP_FOLDER, SP_KEY_PREFIX,
SP_PROBE_PREFIX, GRAPH_TENANT, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
GRAPH_SCOPES, plus the existing R2_* variables.
"""

import argparse
import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import requests
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"

HOST = os.environ.get("SP_HOST", "3ie.sharepoint.com")
SITE_PATH = os.environ.get("SP_SITE_PATH", "DEPChatbot")
FOLDER = os.environ.get("SP_FOLDER", "General/data/full_text_paywall")
KEY_PREFIX = os.environ.get("SP_KEY_PREFIX", "_staging/full_text_paywall/")
PROBE_PREFIX = os.environ.get("SP_PROBE_PREFIX", "_probe/sharepoint/")

# Prefixes the live pipeline reads and processes. --sync refuses these without --yes.
PRODUCTION_PREFIXES = ("input-pdfs/", "rags/")

TENANT = os.environ.get("GRAPH_TENANT", "common")
# Microsoft Graph Command Line Tools: a Microsoft first-party public client.
CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")
SCOPES = os.environ.get(
    "GRAPH_SCOPES",
    "https://graph.microsoft.com/Sites.Read.All "
    "https://graph.microsoft.com/Files.Read.All offline_access",
)

CACHE = Path(".graph_token.json")
MAX_PROBE_BYTES = int(os.environ.get("SP_MAX_PROBE_BYTES", 25 * 1024 * 1024))
CHUNK = 1 << 20

_TOKEN = {"value": None, "expires_at": 0.0}
_TOKEN_LOCK = threading.Lock()
_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32))
_S3 = None


# --------------------------------------------------------------------------- R2

def r2_client():
    global _S3
    if _S3 is None:
        _S3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(max_pool_connections=64),
        )
    return _S3


def bucket_name():
    return os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")


def content_type(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def cmd_r2_only():
    s3, bucket = r2_client(), bucket_name()
    print(f"bucket: {bucket}")
    root = s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
    print("root reachable:", root.get("KeyCount") == 0 or "Contents" in root)
    sample = s3.list_objects_v2(Bucket=bucket, Prefix="input-pdfs/", MaxKeys=5)
    print("input-pdfs/ sample:", sample.get("KeyCount", 0))
    for o in sample.get("Contents", []):
        print(f"  {o['Key']}  {o['Size']}")
    print("R2 OK")


# ------------------------------------------------------------------------ auth

def save_cache(tok):
    tok = dict(tok)
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
    CACHE.write_text(json.dumps(tok))
    try:
        os.chmod(CACHE, 0o600)
    except OSError:
        pass


def load_cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def cmd_auth():
    dc = requests.post(
        f"{LOGIN}/{TENANT}/oauth2/v2.0/devicecode",
        data={"client_id": CLIENT_ID, "scope": SCOPES},
        timeout=30,
    ).json()
    if "device_code" not in dc:
        print("device-code error:")
        print(json.dumps(dc, indent=2))
        sys.exit(1)

    print("=" * 64)
    print("SIGN IN REQUIRED")
    print("  open:  ", dc["verification_uri"])
    print("  code:  ", dc["user_code"])
    print("=" * 64, flush=True)

    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        tok = requests.post(
            f"{LOGIN}/{TENANT}/oauth2/v2.0/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": dc["device_code"],
            },
            timeout=30,
        ).json()
        if "access_token" in tok:
            save_cache(tok)
            print("signed in; token cached to .graph_token.json")
            return
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        print("token error:")
        print(json.dumps(tok, indent=2))
        sys.exit(1)
    print("timed out waiting for sign-in")
    sys.exit(1)


def _acquire_token():
    """Return (access_token, expires_in). Used by the token provider."""
    if CLIENT_SECRET:
        r = requests.post(
            f"{LOGIN}/{TENANT}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"client-credentials error ({r.status_code}): {r.text[:400]}")
        j = r.json()
        return j["access_token"], j.get("expires_in", 3600)

    cache = load_cache()
    if cache.get("refresh_token"):
        r = requests.post(
            f"{LOGIN}/{TENANT}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": cache["refresh_token"],
                "scope": SCOPES,
            },
            timeout=30,
        )
        if r.status_code == 200:
            j = r.json()
            save_cache(j)
            return j["access_token"], j.get("expires_in", 3600)
    raise RuntimeError("no valid token; run: python scripts/sharepoint_r2_probe.py --auth")


def get_token(force=False):
    """Return a valid access token, refreshing when expired or force=True."""
    with _TOKEN_LOCK:
        if not force and _TOKEN["value"] and _TOKEN["expires_at"] > time.time() + 60:
            return _TOKEN["value"]
        access, expires_in = _acquire_token()
        _TOKEN["value"] = access
        _TOKEN["expires_at"] = time.time() + int(expires_in)
        return _TOKEN["value"]


# ----------------------------------------------------------------------- graph

def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def graph_get(token_provider, url, **kw):
    if url.startswith("/"):
        url = GRAPH + url
    timeout = kw.pop("timeout", 90)
    refreshed = False
    for attempt in range(8):
        r = _SESSION.get(url, headers=hdr(token_provider()), timeout=timeout, **kw)
        if r.status_code == 401 and not refreshed:
            token_provider(force=True)
            refreshed = True
            continue
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", min(2 ** attempt, 60))))
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 30))
            continue
        return r
    return r


def resolve_item(token_provider, folder):
    site = graph_get(token_provider, f"/sites/{HOST}:/sites/{SITE_PATH}").json()
    if "id" not in site:
        print("site lookup failed:", json.dumps(site, indent=2)[:500])
        sys.exit(1)
    print("site:", site.get("displayName"), site.get("webUrl"))
    drives = graph_get(token_provider, f"/sites/{site['id']}/drives").json().get("value", [])
    for d in drives:
        r = graph_get(token_provider, f"/drives/{d['id']}/root:/{folder}")
        if r.status_code == 200:
            item = r.json()
            kind = "file" if "file" in item else "folder"
            print("drive:", d.get("name"), f"| {kind}:", item.get("name"))
            return d["id"], item
    print(f"path not found in any drive: {folder}")
    sys.exit(1)


def iter_files(token_provider, drive_id, item_id, prefix="", pdf_only=False):
    url = f"/drives/{drive_id}/items/{item_id}/children?$top=200"
    while url:
        r = graph_get(token_provider, url)
        if r.status_code != 200:
            raise RuntimeError(f"listing failed ({r.status_code}) for {url}: {r.text[:200]}")
        data = r.json()
        for it in data.get("value", []):
            if "folder" in it:
                yield from iter_files(
                    token_provider, drive_id, it["id"], f"{prefix}{it['name']}/", pdf_only
                )
            elif "file" in it:
                if pdf_only and not it["name"].lower().endswith(".pdf"):
                    continue
                yield {
                    "id": it["id"],
                    "name": it["name"],
                    "rel": f"{prefix}{it['name']}",
                    "size": it.get("size", 0),
                }
        url = data.get("@odata.nextLink")


def download(token_provider, drive_id, item_id, dest):
    url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/content"
    refreshed = False
    for attempt in range(6):
        with _SESSION.get(
            url,
            headers=hdr(token_provider()),
            stream=True,
            allow_redirects=True,
            timeout=(30, 600),
        ) as r:
            if r.status_code == 401 and not refreshed:
                token_provider(force=True)
                refreshed = True
                continue
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(min(2 ** attempt, 30))
                continue
            r.raise_for_status()
            written = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(CHUNK):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
            return written
    raise RuntimeError(f"download failed after retries: {item_id}")


def collect(token_provider, folder, pdf_only=False):
    drive_id, item = resolve_item(token_provider, folder)
    if "file" in item:
        return drive_id, [{
            "id": item["id"],
            "name": item["name"],
            "rel": item["name"],
            "size": item.get("size", 0),
        }]
    files = list(iter_files(token_provider, drive_id, item["id"], pdf_only=pdf_only))
    return drive_id, files


def cmd_list(token_provider, folder):
    drive_id, files = collect(token_provider, folder, pdf_only=False)
    total = sum(f["size"] for f in files)
    pdfs = [f for f in files if f["name"].lower().endswith(".pdf")]
    print(f"files: {len(files)} ({len(pdfs)} pdf)  total: {total / 1e9:.2f} GB")
    print("largest 5:")
    for f in sorted(files, key=lambda x: -x["size"])[:5]:
        print(f"  {f['size'] / 1e6:9.1f} MB  {f['rel']}")
    print("smallest 5:")
    for f in sorted(files, key=lambda x: x["size"])[:5]:
        print(f"  {f['size'] / 1e6:9.1f} MB  {f['rel']}")
    return drive_id, files


def cmd_probe(token_provider, folder, clean=False, pdf_only=True):
    drive_id, files = collect(token_provider, folder, pdf_only=pdf_only)
    cands = [f for f in files if 0 < f["size"] <= MAX_PROBE_BYTES]
    if not cands:
        print(f"no file within the probe cap ({MAX_PROBE_BYTES} bytes)")
        sys.exit(1)
    f = min(cands, key=lambda x: x["size"])
    key = f"{PROBE_PREFIX}{f['name']}"
    print(f"probe file: {f['rel']} ({f['size']} bytes) -> {key}")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        path = tmp.name
    try:
        written = download(token_provider, drive_id, f["id"], path)
        print(f"downloaded {written} bytes")
        s3 = r2_client()
        s3.upload_file(
            path, bucket_name(), key, ExtraArgs={"ContentType": content_type(f["name"])}
        )
        head = s3.head_object(Bucket=bucket_name(), Key=key)
        print(f"uploaded r2://{bucket_name()}/{key}")
        print(f"verified: {head['ContentLength']} bytes, etag {head['ETag']}")
        if clean:
            s3.delete_object(Bucket=bucket_name(), Key=key)
            print("probe object deleted")
    finally:
        os.unlink(path)
    print("PROBE OK")


def existing_keys(s3, prefix):
    pag = s3.get_paginator("list_objects_v2")
    keys = set()
    for page in pag.paginate(Bucket=bucket_name(), Prefix=prefix):
        for o in page.get("Contents", []):
            keys.add(o["Key"])
    return keys


def cmd_sync(token_provider, folder, prefix, force=False, dry_run=False, pdf_only=True,
             workers=8, limit=0):
    drive_id, files = collect(token_provider, folder, pdf_only=pdf_only)
    total = sum(f["size"] for f in files)
    s3 = r2_client()
    print(
        f"syncing {len(files)} files ({total / 1e9:.2f} GB) to "
        f"r2://{bucket_name()}/{prefix} with {workers} workers",
        flush=True,
    )

    if force:
        todo = list(files)
    else:
        present = existing_keys(s3, prefix)
        todo = [f for f in files if f"{prefix}{f['rel']}" not in present]
    skipped = len(files) - len(todo)
    if limit:
        todo = todo[:limit]

    if dry_run:
        for f in todo:
            print(f"  would copy {f['rel']}")
        print(f"dry run: {len(todo)} to copy, {skipped} skipped")
        return

    def work(f):
        key = f"{prefix}{f['rel']}"
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name
        try:
            download(token_provider, drive_id, f["id"], path)
            s3.upload_file(
                path, bucket_name(), key, ExtraArgs={"ContentType": content_type(f["name"])}
            )
            return f, f["size"], None
        except Exception as e:
            return f, 0, e
        finally:
            os.unlink(path)

    done = failed = 0
    moved = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, f) for f in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            f, size, err = fut.result()
            if err is None:
                done += 1
                moved += size
            else:
                failed += 1
                print(f"  FAILED {f['rel']}: {err}", flush=True)
            if i % 100 == 0 or i == len(todo):
                print(
                    f"  [{i}/{len(todo)}] {done} copied, {failed} failed, "
                    f"{moved / 1e9:.2f} GB",
                    flush=True,
                )
    print(
        f"done: {done} copied, {skipped} skipped, {failed} failed ({moved / 1e9:.2f} GB moved)"
    )
    if failed:
        sys.exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r2-only", action="store_true")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--clean", action="store_true", help="delete the probe object after upload")
    ap.add_argument("--force", action="store_true", help="re-copy keys that already exist")
    ap.add_argument("--dry-run", action="store_true", help="list what --sync would copy")
    ap.add_argument("--prefix", help="R2 key prefix for --sync (default SP_KEY_PREFIX)")
    ap.add_argument("--folder", help="source path within the library (default SP_FOLDER)")
    ap.add_argument("--all-files", action="store_true", help="copy every file, not only .pdf")
    ap.add_argument("--yes", action="store_true", help="confirm writes to a production prefix")
    ap.add_argument("--workers", type=int, default=8, help="parallel transfers for --sync")
    ap.add_argument("--limit", type=int, default=0, help="cap files processed by --sync (0 = all)")
    args = ap.parse_args()

    if args.r2_only:
        cmd_r2_only()
        return
    if args.auth:
        cmd_auth()
        return

    folder = args.folder or FOLDER
    prefix = args.prefix or KEY_PREFIX
    if args.sync and prefix.startswith(PRODUCTION_PREFIXES) and not args.yes and not args.dry_run:
        print(
            f"refusing to write to production prefix '{prefix}' without --yes "
            f"(use --dry-run to preview)"
        )
        sys.exit(2)

    token_provider = get_token
    try:
        if args.list:
            cmd_list(token_provider, folder)
        elif args.probe:
            cmd_probe(token_provider, folder, clean=args.clean, pdf_only=not args.all_files)
        elif args.sync:
            cmd_sync(
                token_provider,
                folder,
                prefix,
                force=args.force,
                dry_run=args.dry_run,
                pdf_only=not args.all_files,
                workers=args.workers,
                limit=args.limit,
            )
        else:
            ap.print_help()
    except RuntimeError as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

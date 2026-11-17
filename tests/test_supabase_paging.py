"""Tests for the Supabase paging helpers.

The helpers exist because PostgREST caps a single response at 1,000 rows. These tests
drive a fake query builder so the paging and chunking logic is checked without a
database.
"""

from src.auth.supabase_auth import fetch_all_rows, update_by_ids


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Fake Supabase select builder that honours ``range`` over an in-memory list."""

    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls
        self._start = 0
        self._end = 0

    def range(self, start, end):
        self._start, self._end = start, end
        self._calls.append((start, end))
        return self

    def execute(self):
        return _Resp(self._rows[self._start:self._end + 1])


def _make_query(rows, calls):
    return lambda: _Query(rows, calls)


def test_returns_every_row_across_pages():
    rows = [{"id": i} for i in range(2500)]
    calls = []
    out = fetch_all_rows(_make_query(rows, calls))
    assert len(out) == 2500
    assert out[0]["id"] == 0
    assert out[-1]["id"] == 2499
    # Three pages requested: 0-999, 1000-1999, 2000-2999.
    assert calls == [(0, 999), (1000, 1999), (2000, 2999)]


def test_exact_multiple_of_page_stops_after_empty_page():
    rows = [{"id": i} for i in range(1000)]
    calls = []
    out = fetch_all_rows(_make_query(rows, calls))
    assert len(out) == 1000
    # A full page is ambiguous, so one more request confirms the end.
    assert calls == [(0, 999), (1000, 1999)]


def test_empty_table_returns_empty_list():
    calls = []
    assert fetch_all_rows(_make_query([], calls)) == []
    assert calls == [(0, 999)]


def test_custom_page_size():
    rows = [{"id": i} for i in range(7)]
    calls = []
    out = fetch_all_rows(_make_query(rows, calls), page_size=3)
    assert len(out) == 7
    assert calls == [(0, 2), (3, 5), (6, 8)]


class _UpdateQuery:
    def __init__(self, calls):
        self._calls = calls
        self._payload = None

    def update(self, payload):
        self._payload = payload
        return self

    def in_(self, column, ids):
        self._calls.append((column, list(ids), self._payload))
        return self

    def execute(self):
        return _Resp([])


class _FakeClient:
    def __init__(self, calls):
        self._calls = calls

    def table(self, name):
        return _UpdateQuery(self._calls)


def test_update_by_ids_chunks_the_id_filter():
    calls = []
    ids = list(range(1200))
    update_by_ids(_FakeClient(calls), "documents", ids, {"status": "processing"}, chunk=500)
    assert [len(c[1]) for c in calls] == [500, 500, 200]
    assert all(c[0] == "id" for c in calls)
    assert all(c[2] == {"status": "processing"} for c in calls)


def test_update_by_ids_with_no_ids_makes_no_request():
    calls = []
    update_by_ids(_FakeClient(calls), "documents", [], {"status": "processing"})
    assert calls == []

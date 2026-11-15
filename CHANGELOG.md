# Changelog

All notable changes to DevChat v2.0 are documented in this file.

## [2.0.13] - 2026-11-15

### Added
- **A bounded second pass over the outcomes the paper claims and no row carries.** `src/extraction/second_pass.py` re-reads only the units that mention a missing outcome, eight tables and eight text spans per document, and merges its rows with the first pass by outcome, arm and estimate, so a repeat fills a gap instead of adding a row. A sentence is selected on the outcome's distinctive word, because a paper names an outcome differently in prose. On four papers it read 32 units, added 71 rows, and recovered 121295229's `2.404`, which the document prints as `2.40`. The cap is per kind because a shared budget let eight tables consume it and left one sentence read.
- **A recall gate that runs on a schedule and fails when recall drops.** `evaluation/quality_gate.py`, run weekly and on changes to the extraction or evaluation path by `.github/workflows/quality-gate.yml`, reads the database and the key, calls no model, and compares the matched count with `evaluation/results/recall_baseline.json`; a fall fails the run. `--update-baseline` rewrites the baseline deliberately. The repository is public and the key is 3ie's own coding, so `data/` is not in it; CI reads the key from the private bucket at `reference/8WR QEX Combined.xlsx` with repository storage credentials, and the first CI run reproduced the local figures (304 of 325 estimates, 284 of 305 standard errors, 588 of 630). Without those credentials it reports a skip with a notice.
- **A retrieval queue and an attainable recall figure.** `evaluation/retrieval_queue.py` gives every mapped document a verdict. A review or a summary is not the study, so its missing values are set aside from the denominator and the study is queued for retrieval: paper 121766336 is the only one, with 18 estimates and 18 standard errors. A key that cites a page the document does not have is treated separately, because a journal article numbers its pages from the journal; 121294795 and 121295229 keep their values in the denominator.
- **Wide and panel tables are read one estimate column at a time.** `split_estimate_columns` gives each estimate column its own view, named by its header, which the model is told is the arm; grouped headers keep their group number, a continuation table whose first row is data is named by position, and columns that name a statistic or hold only parenthesised numbers are left out. The whole table is read as well, and `merge_reads` keeps one row per outcome and estimate value, filling a standard error seen in either read, so the change adds coverage instead of replacing it. Paper 122182716 stores 94 rows against 36, and both of its hand-typed values are found. Cost, measured over twelve documents: 341 tables become 963 views (2.82x), about 3.8x where the whole read is kept too.

### Fixed
- **Garbled-page repair actually replaced the pages.** The Docling path printed the number of pages it detected, not the number it replaced, and a refused or non-table transcription was dropped silently, so a run could leave every garbled page in place while reporting success. The repair now requires a table in the transcription, retries once with a table-only prompt, keeps the original text when the retry fails (fail open), and reports `replaced` of `detected` plus the pages it left.
- **Transcription prompt.** The old prompt asked for a verbatim page and invited a refusal ("I can't reproduce the full page verbatim"); the model returned a summary. The prompt now frames the page as a text corpus and asks for the page's text with tables as Markdown pipe tables, which the model follows on the pages tested.
- **Repair page cap** raised from 12 to 40, after a paper with 26 garbled pages kept 2 of them (only the first 12 were ever requested).
- **Repaired pages are read from the image again.** A repaired page became ordinary text, so the automatic vision decision no longer selected it and the estimates on it were lost. Repaired pages are now flagged and stay in the vision set. Paper 121328483 stored zero table rows until this was fixed.
- **Pipe tables typed as text.** Docling returns its largest layout tables as ordinary text; paper 121328483 has its two-year and three-year results tables (pages 18 to 20) typed that way, so the table reader never saw them and the document matched none of the 13 hand-typed estimates. Text items that are Markdown pipe tables are now typed as tables before extraction.
- **`pymupdf` in the base image.** The estimate and study-fact steps ran on an image without it, so the vision fallback failed with `ModuleNotFoundError: No module named 'fitz'` (3 documents, 0 rows). Both steps now run.
- **Each repaired page is read once.** A repaired transcription is left as text so the vision pass reads that page, and a page whose pipe text was retyped as a table is left out of the no-table full scan, which otherwise read the same page twice. The prose reader also stands down for a document whose only tables were repaired. The retry shares one rendered page image, and the budget is configurable (`REPAIR_MAX_PAGES` default 40, `REPAIR_RETRY=0` for one call per page).
- **The recall audit read at most 1000 rows per document.** PostgREST returns at most that many per request whatever `limit` asks for, so `error_report.py` and `missing_estimates_audit.py` compared large documents against their first 1000 rows and reported stored values as missing (paper 121058367's `-0.049` is on page 130). `evaluation/stored_rows.py` now pages every read.
- **Printed precision is not a gap.** A key value of `2.404` against a printed `2.40` is the same number at coarser precision; it is now a match, while `691.179` against a printed `691.149` stays a mismatch because the difference is larger than half of the last decimal printed. The same module holds that rule, and `classify_miss` splits `exact`, `rounded` and `absent`.
- **`evaluation/table_coverage.py` reads every results table and reports the estimate-shaped cells with no stored row on the same page.** It needs no hand-typed key, calls no model, and is the check that finds dropped cells after an ingestion batch. On paper 122182716 it reported 32 of 43 cells unstored on page 13 before the column views. In CI it reads all 97 documents and reports 16,934 estimate-shaped cells, 5,609 with no stored row; that is a review queue rather than a defect count, because control means and appendix replications qualify, and it needs calibration against a sample before it drives work.
- **A row label with a units note was dropped as a non-outcome.** `is_non_outcome_label` matched its cues anywhere in the label, so `Per capita income (BDT constant price)` was dropped for the cue "constant", and paper 122182716's `936` with it. Cues are matched against the label with parenthetical units removed, in the same normalised form as the cue, which also restored `F-statistic` once hyphens were normalised.

### Measured
Against the hand-typed key (36 studies, 325 estimates, 305 standard errors), after re-parsing and re-extracting the affected papers and after the wide-table and second-pass work: 304 estimates (94%) and 284 standard errors (93%), against 300 and 284 as last reported. Paper 121328483 is restored from 0 of 13 to 13 of 13, no garbled tables are left in the three re-parsed documents, and paper 122182716's two values are now found. Setting aside the 36 values for 121766336, whose document is a summary without the cited table, attainable recall is 588 of 594 values (99%).

Of the values still missing, 3 estimates and 3 standard errors sit outside the retrieval queue and all are differences between the key and what the papers print: 122182715's `57.645` and `192.975` against printed `57.02` and `192.974`, 121294795's `92.8` which is not in the text, and the standard errors `16.96`, `4.24` and `691.179` against printed `16.698`, `4.224` and `691.149`.

The 18 misses for 121766336 (Bab Amal, Egypt) were re-checked. The study paper exists (Assaad, Osman, Parienté and Valente, *How Big Does a "Big Push" Need to Be?*) but reports rounded values that differ from the key, and the 12-page policy brief held for that id prints its results as figures, not as the estimate table the key cites. A vision pass over the brief returned 27 rows and none of the 18 values, so they remain outside the collection rather than unexplained; `evaluation/retrieval_queue.py` now lists them for retrieval.

---

## [2.0.12] - 2026-11-14

### Added
- **Table interpretation before extraction**: a deterministic reader for the table's structure (columns, rows, notes, abbreviations, and arithmetic checks) and a table type (results, descriptive, review), with the results passed to the model as a hint.
- **Filters**: descriptive tables are skipped without a model call, non-outcome rows (Observations, R², Constant, Controls, means) are dropped, and columns of means and standard deviations are not treated as estimates.
- **Vision fallback**: pages whose tables are images, whose text is garbled, or which print values on a figure are read from the page image, capped per document. Garbled pages can also be transcribed to clean Markdown for retrieval.
- **Prose extraction** for documents with no tables, grounded by requiring the quoted sentence to appear in the paper.
- **Outcome confirmation**: the paper's stated primary and secondary outcomes are compared with the extracted rows and any missing one is logged for review.
- **Provenance checks** for a policy brief that is not the study's paper, and for reviews, reflections and syntheses.

### Measured
Against the hand-typed key (36 studies, 325 estimates, 305 standard errors): 300 estimates (92%) and 284 standard errors (93%) matched, which is 97% of the 307 values whose papers are present in the collection, with 2 real misses left.

---

## [2.0.11] - 2026-11-13

### Added
- **In-app PDF reader** (`react-pdf` + `pdfjs-dist`), replacing the browser iframe viewer: zoom, page navigation, full-text search, cited-passage highlighting, and windowed page rendering so long PDFs open quickly. Loaded client-side only.
- **Role filter before embedding**: paragraphs that are not a document's own evidence (references, boilerplate, background, other studies' findings) are dropped, and each abstract is always kept. Applied on the admin ingest route and on `scripts/ingest_documents.py`; `INDEX_ROLE_FILTER` now defaults on. The graduation collection was re-indexed (98 documents).
- **Quote verification**: a supporting quote must be a verbatim span of the passages. A reformatted quote is snapped to its source sentence, and one that cannot be found is dropped, so a citation or PDF highlight never points at text the paper does not contain.
- Retry with backoff for search RPCs, so a slow database delays a query instead of failing it.

### Changed
- The reader judges relevance by the kind of question (effect, implementation, context, design, cost, mechanism), not only by reported results, so questions that are not about effects return evidence.
- The secondhand guard also flags prose attributions ("previous studies find", "the literature shows").

### Fixed
- Page metadata collapsed to the last page in the role-filtered chunking path, which would have broken PDF highlighting.
- Console crash on non-ASCII log output on Windows (cp1252).

### Measured (211-question usage study)
- Kind-aware reader: relevant studies per question 15.2 to 18.3 overall, implementation 0.7 to 1.6.
- Filtered index: noise paragraphs 31% to 6% of what the reader is shown and 8.6% to 1.2% of quotes; relevant studies per question up 32% at equal reading volume; benchmark gate passed (0.566 vs 0.552).
- Quote verification: quotes not verbatim 141 (2.6%) to 0; supporting quotes 5,367 to 4,991; cited readings 3,392 to 3,448.

---

## [2.0.10] - 2026-01-15

### Changed
- Complete documentation overhaul: SETUP_TRACKER.md and ROADMAP.md rewritten with clear status dashboards
- Removed verbose aspirational code examples from ROADMAP.md (434→143 lines)

---

## [2.0.9] - 2026-01-14

### Added
- **Extraction Pipeline V2 SOTA** - Production table extraction using BeautifulSoup
  - 100% match on Bossuroy Table 1 (18/18 rows)
  - Rules-based + LLM classification for results vs descriptive tables
  - Output: CSV + JSON to `extraction_pipeline/outputs/{study_id}/`

### Changed
- Project reorganization: renamed docs, archived old extractors (v10-v17)
- Moved FURTHER_IMPROVEMENTS.md → docs/ROADMAP.md
- Moved EVALUATION_FRAMEWORK.md → docs/EVALUATION.md

---

## [2.0.8] - 2026-01-08

### Added
- **Contextual Retrieval** - Anthropic's 49% improvement technique
  - LLM-generated context prefixes for each chunk
  - New Qdrant fields: `contextual_prefix`, `text_with_context`
  - 97 PDFs reprocessed, 6,769 chunks with prefixes

---

## [2.0.7] - 2026-01-07

### Added
- **Modal Pipeline Refactoring** - Modular architecture
  - Split 1700-line modal_mineru.py into 8 modules in modal_lib/
  - Entry point now 230 lines (87% reduction)
- **Study Design Classification** - 22 types with LLM classifier
  - StudyDesignBadge frontend component
  - 96 documents classified (34 RCT, 10 DiD, etc.)
- **Parent-Child Chunking** - Small chunks for search, parent for context
  - ParentChildChunker in src/ingestion/chunking.py

### Fixed
- Webhook timeout via `.spawn()` background processing
- Stale job auto-cleanup (>30 min marked as failed)

---

## [2.0.6] - 2026-01-06

### Added
- **PDF Citation Highlighting** - PyMuPDF with inline viewer
  - Endpoint: `/rags/{id}/documents/{doc_id}/pdf-highlighted`
  - Toggle button to switch Evidence panel ↔ PDF viewer
  - Evidence snippet card with copy button
- **Prompt Customization** - Per-RAG extraction/synthesis prompts
  - Prompt history with restore (max 10 versions)
  - Safety: acknowledge_risk checkbox
- **Chat History Caching** - Citations robustly cached to Supabase

---

## [2.0.5] - 2026-01-03

### Added
- Sparse vector support in Modal indexing for hybrid search
- "Mark as reviewed" checkbox in metadata editor (save doesn't auto-mark)
- BM25-style sparse vectors for keyword matching

### Fixed
- Qdrant collection name mismatch (dashes vs no-dashes)
- Fallback to dense-only search when collection lacks sparse vectors
- Metadata panel scroll staying within card bounds
- Compact header when panel is narrow (1/3 width)

### Changed
- Modal now looks up collection name from database instead of guessing
- Reorganized repository (archived old files, moved eval scripts)

---

## [2.0.4] - 2026-01-02

### Added
- Backend pagination for document/metadata lists
- Hallucination prevention (0.8 similarity threshold for metadata enrichment)

### Fixed
- Layout regression where document list disappeared when editing
- Flexbox scroll issues in metadata panel

---

## [2.0.3] - 2025-12-31

### Added
- Multi-tenant RAG platform with Supabase auth
- Per-user RAG projects with isolated Qdrant collections
- Public RAG sharing via slugs (/r/{slug})
- Full Documents/Metadata/Processing/Settings tabs
- Drag-drop and batch PDF upload
- Content-hash deduplication

### Changed
- Migrated from single collection to per-project collections
- Added Row Level Security to all tables

---

## [2.0.2] - 2025-12-28

### Added
- Claim Ledger synthesis for grounded responses
- Hybrid BM25+Dense search (Qdrant native)
- Contextual retrieval with document prefixes
- Post-hoc verification (NLI-based)
- Citation coverage validator

### Achieved
- **Faithfulness: 0.699** (target: 0.70+) ✅
- **Citation Recall: 1.000** ✅
- **Citation Precision: 1.000** ✅

---

## [2.0.1] - 2025-12-22

### Added
- Side-by-side metadata editor with PDF viewer
- Item types (article, book, report, thesis, etc.)
- Volume, issue, pages extraction
- 256-word chunks for better RAG precision

### Fixed
- False positive bug in has_useful_content detection

---

## [2.0.0] - 2025-12-17

### Initial Release
- FastAPI backend with modular routes
- Next.js 15 frontend
- MinerU PDF processing on Modal
- Cohere embed-v4 embeddings
- CrossRef/OpenAlex metadata enrichment
- Qdrant vector storage
- PostgreSQL metadata store
- Langfuse observability

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 2.0.10 | 2026-01-15 | Documentation overhaul |
| 2.0.9 | 2026-01-14 | Extraction Pipeline V2 SOTA |
| 2.0.8 | 2026-01-08 | Contextual Retrieval |
| 2.0.7 | 2026-01-07 | Modal refactoring, Study Design, Parent-Child |
| 2.0.6 | 2026-01-06 | PDF highlighting, Prompt customization |
| 2.0.5 | 2026-01-03 | Sparse vectors, repo cleanup |
| 2.0.4 | 2026-01-02 | Pagination, hallucination fix |
| 2.0.3 | 2025-12-31 | Multi-tenant RAG platform |
| 2.0.2 | 2025-12-28 | Citation quality at target |
| 2.0.1 | 2025-12-22 | Metadata editor, item types |
| 2.0.0 | 2025-12-17 | Initial SOTA release |

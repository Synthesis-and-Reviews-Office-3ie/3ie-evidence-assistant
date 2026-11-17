# Changelog

All notable changes to DevChat v2.0 are documented in this file.

## [2.0.14] - 2026-11-17

### Fixed
- **Every count that read past 1,000 rows was wrong.** Supabase returns at most 1,000 rows from a single request
  and does not warn, so the queries that fetched a whole project's documents silently truncated. Ten call sites
  were affected: the Processing tab's stat cards and the "Process Pending" selection (`api/routes/rags.py`), the
  worker's document lookup before it writes metadata (`infrastructure/modal_lib/processing.py`), `doc_keys` in
  `src/vectorstore/chunk_store.py`, the Zotero matcher, the study-design classifier, the metadata refresh, and the
  two admin dashboards. A project with 16,468 documents showed "Pending 1000"; it now shows 16,468.

### Added
- **Paging helpers.** `src/auth/supabase_auth.py` gains `fetch_all_rows`, which pages a select to completion, and
  `update_by_ids`, which chunks an id-filtered update. `tests/test_supabase_paging.py` covers both.
- **Postgres aggregates for the admin counts.** `supabase/migrations/20261117000200_admin_count_functions.sql`
  adds `document_counts_by_project()` and `usage_by_user()`, so the admin dashboards answer with one small
  response. The Python helpers fall back to paging when the functions are absent.
- **SharePoint to R2 ingest.** `scripts/sharepoint_r2_probe.py` signs in by device code, resolves a document
  library folder through Microsoft Graph and streams files into R2, so a 20 GB corpus moves server-side rather
  than through a machine. `scripts/promote_staging_to_project.py` copies staged PDFs into a project's
  `rags/{project_id}/input-pdfs/` prefix under the app's `{sha256[:12]}_{name}.pdf` convention and inserts the
  matching `documents` rows.

## [2.0.13] - 2026-11-15

### Added
- **A bounded second pass over the outcomes the paper claims and no row carries.** `src/extraction/second_pass.py` re-reads only the units that mention a missing outcome, eight tables and eight text spans per document, and merges its rows with the first pass by outcome, arm and estimate, so a repeat fills a gap instead of adding a row. A sentence is selected on the outcome's distinctive word, because a paper names an outcome differently in prose. On four papers it read 32 units, added 71 rows, and recovered 121295229's `2.404`, which the document prints as `2.40`. The cap is per kind because a shared budget let eight tables consume it and left one sentence read.
- **Control statistics and standardised columns.** `scripts/db_migrate.py` applied the control-stats migration, so the earlier note that this needed the SQL editor was wrong, and a second migration adds `effect_size_d`, `var_d`, `hedges_g`, `var_g` and `se_g`. The reader now captures the control mean and standard deviation, each accepted only when its cell appears in the table as printed; paper 122182715 carries a control SD on 220 of its 315 rows. The standardised columns are written whenever the inputs exist, but `hedges_g` needs per-arm counts and those tables print one pooled Obs per column, so they stay null rather than being guessed.
- **An estimate column without stars was never read.** Paper 122182716's third panel column prints `-398 (-0.82)` with a t statistic and no stars, and the column split selected only columns with a starred value or a standard-error row beneath, so its five cells were never read. The test now accepts an estimate with a parenthesised statistic. After re-extracting, pages 13 and 14 have no missing cells and the paper stores 117 rows against 94. The triage also now classifies tables of means (no stars, `value (se)` cells), equality-test p-values and covariate rows, which took the six re-extracted papers from 419 unexplained cells to 3 of 484: one merged cell whose row label the parser did not carry, and two attendance results in an appendix. The rest were not reader errors; the commonest shape is a regression table with outcomes in the columns and covariates down the rows.
- **Two table shapes kept values out.** A header reading "Lower Bounds - (2) - 0.25 SD" was taken for a standard-deviation column because it contains "SD", so paper 121058369's appendix lost five of seven columns; the header test is now anchored to a statistic name. A table printing stars in the column beside the value left "-81.6" unstarred and the column unread; a value column followed by a star-only column is now a view and the stars are joined to the value. Re-extraction recovered both values.
- **Two precision measures, six more papers, two more fixes.** Value identification (is the stored number printed
  where the row says it is) is 1,085 of 1,097 rows, 98.9 percent; parameter identification (is the stored standard
  error printed) is 819 of 819, and 819 of 1,097 rows carry one at all, because several of these papers print no
  standard error. Two faults came out of it: a label wrapped at a hyphen (diversifica- tion) defeated the merge and
  stored one estimate twice, and the arm test counted an Observations row as an outcome, so a table whose only arm
  row is Treatment was still split by column and each estimate carried its column heading as the arm. Both are
  fixed and paper 121378494 now reads arm Treatment on every row.
- **Three precision fixes from a fifty-row sample.** Reading fifty stored rows across three papers found every
  value printed, but only 38 of them were treatment effects: twelve were levels taken from prose, six were
  duplicates where a column marker made one row look like two, and the arm field was wrong where a table's single
  body row was the arm. The prose reader now rejects a share written as "N% of" unless a change word stands
  before it, a single-row table whose row names an arm is read whole, and the merge strips a leading column
  marker before comparing outcomes. On five re-extracted papers, 53 of 54 rows are now treatment effects, with
  one hyphenated duplicate and the arm labels still to fix; recall is unchanged at 854 of 854.
- **The t statistic, the confidence bounds and the cell kind are stored.** The table kept the standard error and
  the interval as text only, so a t-only table left no uncertainty figure and an interval could not be queried.
  	_stat, ci_low, ci_high and se_kind are added and written with each row; existing rows are null until
  they are re-extracted, and null means not printed rather than zero.
- **A coefficient's second cell is now checked before it is stored.** Across 30,801 rows, 23,357 carry a
  standard error, 218 a confidence interval and 7,226 neither (a t statistic or nothing printed). Thirty-seven
  standard errors were zero, twenty-seven intervals excluded their own estimate, and twenty-nine p-values
  contradicted the stars on the estimate. The reader now drops a zero standard error, an interval that excludes
  its estimate and a p-value that contradicts its stars, with a test each; the stored rows were cleared and the
  checks now read clean. All 412 standard errors in the key match, which confirms the classification.
- **Standardised effect sizes are captured wherever a paper supplies the inputs.** The reader now takes a
  per-column observation count when those counts differ by column, the control column's count from its header,
  the two arm counts joined per page and outcome, and the control deviation joined to an effect row by outcome
  name. Re-extracting the seventeen documents that print a control deviation gave 4,125 deviations, 2,639 treated
  counts and 281 control counts, and 62 rows with all four inputs, which now carry `d`, `g` and `se(g)`. That is
  the limit of the papers rather than of the arithmetic: published tables rarely print a control deviation and a
  per-arm count for the same outcome.
- **A table with more than eight estimate columns lost the rest.** The column split stopped at eight, so paper
  121295428's ten-column table and paper 121294984's eighteen-column table were read only in part. The limit is now
  sixteen; re-extracting the three such papers recovered seven cells. The collection is at 56 unexplained cells
  with a real gap of 53, and accuracy is unchanged at 854 of 854.
- **Heterogeneity tables are read as effects by subgroup.** When the rows name subgroups and the columns name
  outcomes, the reader now puts the column heading in outcome and the row label in subgroup; a regression table
  whose columns are models or coefficients is excluded, because those rows are covariates. `subgroup_rows_layout`
  recognises the shape, the prompt explains it and the structure hint states it. After re-extraction 21 stored rows
  carry a subgroup, the collection stands at 66 unexplained cells with a real gap of 63, and accuracy is unchanged
  at 854 of 854.
- **A merged label is carried down to the rows it covers.** A table that merges one label across several rows leaves the later rows with an empty first cell, so their values arrive with no outcome name. `carry_merged_labels` fills the label from the row above when the row carries an estimate and leaves a row holding only a parenthesised standard error alone; re-extracting the three affected papers took their unexplained cells from ten to five. The collection stands at 68 unexplained cells and a real gap of 65, with accuracy unchanged at 854 of 854.
- **Two real faults came out of tracing the last cells.** `is_non_outcome_label` treated "average" as a summary cue, so paper 121354848's "Average price" rows were dropped; it now drops only a bare mean or a control or baseline mean, with tests both ways. The vision reader's default client had no base URL, so a call without a client failed; production always passed one, which hid it. A Spanish "means and difference of means by gender" table is correctly refused by both readers and the triage now names it. The real coverage gap is 70 cells in 20 documents, down from 296.
- **The remaining coverage gap is 107 cells, not 296.** A deep pass compared each remaining cell with every row stored for its study instead of only the rows on its page: 192 of the 296 were already stored, mostly because a table spanning pages stores its rows under the page it starts on. The triage keeps that as `stored on another page`, and the real gap is 107 cells, 0.8 percent of 12,889, across 22 documents with 14 in the largest.
- **The reader is deployed, and the coverage tail is measured from a sample.** The Modal app behind the API now runs the current reader; its trigger endpoint answers 405 to a GET, which is the healthy signal. A thirty-two cell sample showed the remaining queue is a long tail: about a third are shapes and two thirds are estimates printed without stars. The completeness trigger therefore counts estimate-shaped cells rather than rows and asks again whenever the answer is short of that. Unexplained cells stand at 296, down from 1,905.
- **A table is now read to the end.** When a table has at least four labelled rows and the answer covers fewer than 85 percent of them, one more call asks for the rest and the answers are merged; the retry also fires when a table with starred cells was called prose. The budget is twelve retries per document. On the ten worst documents unexplained cells fell from 370 to 169 and on the collection from 519 to 317, with accuracy unchanged at 854 of 854. The triage also stopped calling balance columns, bracketed descriptive means and unstarred household characteristics gaps.
- **The coverage queue was mostly measurement error, and the rest is a reading gap.** Reading the 941 unexplained cells found a Spanish decimal read as an integer (`0,84` as 84), balance and attrition tables whose starred cells are not effects, and `t-test` and `po mean` rows. Fixing those takes the unexplained remainder from 941 to 519 and the unstored cells from 4,231 to 2,242. The 519 that remain are genuine unread values concentrated in about ten documents, and the next fix belongs in extraction: a per-table completeness retry when a results table yields clearly fewer rows than it has outcome rows.
- **The whole collection was re-read in paced batches.** All 98 documents ran through the current reader at one document at a time with a pause, in thirteen batches, with no errors and accuracy unchanged at 854 of 854. Estimate-shaped cells with no stored row fell from 4,231 to 2,510, and the cells the triage cannot explain fell from 1,905 to 941; the rest are tables of means, covariate rows, appendix pages, control means, statistic cells, observation counts and test p-values.
- **Re-extraction runs in paced, resumable batches.** `scripts/reprocess_estimates.py` takes a batch size, runs one document at a time with a pause, and records what it has done in `.cache/reprocess_done.json`, so a later batch resumes instead of repeating work. Four batches re-read 32 of the 98 documents (about 7,500 rows) with no errors and accuracy unchanged at 854 of 854.
- **The audits no longer re-read the estimates table for every study.** The gate and the queue query it once and group by document in memory instead of running about eighty passes over it, which the small instance's disk IO budget did not support; the gate now takes about sixteen seconds. `DOC_CONCURRENCY` is read from the environment so a re-extraction can be run one document at a time, and a write that hits a gateway timeout is retried as a unit. A throttled batch of the five worst-covered documents cut their unstored cells from 944 to 358 with recall unchanged at 854 of 854.
- **Two studies were unmapped because their documents are named by author.** 121058359 (Misha et al. 2019) and 121058372 (Bandiera et al. 2017) sat in the collection as "Misha (2019)" and "Bandiera (2017)", so no filename carried the study id and they were never scored. `evaluation/study_documents.json` assigns each explicitly with its title as evidence, and both then matched every value. All 43 studies are mapped and all 854 values match.
- **Confirmed sheet corrections are recorded, and now applied.** `evaluation/key_errata.json` holds confirmed corrections with the printed value and the evidence, and the audit applies them when it reads the sheet. The seven entries it carried were applied to the workbook itself on 16 November, with the data owner's agreement and a dated backup beside it, so the file is now empty and the mechanism remains for future corrections. Every value the collection can support is matched: 442 of 442 estimates, 412 of 412 standard errors, 854 of 854.
- **The Bab Amal source document was found and added.** The 36 unreachable values were in a three-page companion note, "Bab Amal Policy Brief Details", holding the two estimate tables the sheet cites with all 18 coefficients and standard errors. It was added to the collection, parsed and extracted, and all 36 values now match. The evaluation now maps a study to every document whose filename carries its id, since a study can have more than one, which raised mapped studies from 36 to 41 of 43 and the denominator from 630 to 839 values. Recall on that wider set is 429 of 433 estimates and 401 of 406 standard errors (830 of 839).
- **A figure reading now says which arm and wave it belongs to.** The values read from a chart arrived with the numbers right and the labels missing, because the arm and wave names sit inside the image, so two identical values could not be told apart. The figure prompt now reads the legend and the panel headings and returns the series in `treatment_arm` and the wave in `subgroup`. After re-extracting the Bab Amal brief, the six food-insecurity values carry Full cost, Half cost and Restricted at Midline and Endline, matching the printed figure.
- **A typographic minus made one value look missing.** The sheet writes paper 121294795's coefficient as `−92.8` with a Unicode minus, which the parsers read as positive, so the audit searched for the wrong sign. Four number parsers now normalise the dashes. The five remaining differences are in the sheet rather than the papers, each checked by eye against the printed page and listed in `evaluation/results/key_discrepancies_2026-11-16.md`: three one-digit slips, a standard error rounded differently, and a standard error the paper does not print. Correcting them gives 307 of 325 estimates and 287 of 305 standard errors.
- **A re-run can no longer lose a value.** Extraction replaced a document's rows, so a stochastic read that missed a row lost it, which the gate caught as 304 matched values falling to 303. Every stored row now has a stable `row_key` (md5 of source, page, outcome, arm, subgroup and value, with a unique index), and a replacement run carries forward any stored row whose page and value it did not produce. `--prune` replaces without carrying forward, for a deliberate clean-up. Upserting on `row_key` instead was tried and measured: it cannot lose a row, but it grew paper 121295229 from 260 to 379 rows in one run because the model rewords outcomes, so replacement with the value guard is what ships.
- **A batch insert could not mix readers.** Rows from the table, vision and prose readers have different shapes, and PostgREST rejects a batch whose objects differ (`PGRST102 All object keys must match`), so a document with any vision or prose rows failed to store. Rows are normalised to one key set before writing. The same message had been blocking study cards since they were built: their writer dropped null fields per row, and grouping rows of equal shape fixed it, with 98 cards now written.
- **A recall gate that runs on a schedule and fails when recall drops.** `evaluation/quality_gate.py`, run weekly and on changes to the extraction or evaluation path by `.github/workflows/quality-gate.yml`, reads the database and the key, calls no model, and compares the matched count with `evaluation/results/recall_baseline.json`; a fall fails the run. `--update-baseline` rewrites the baseline deliberately. The repository is public and the key is 3ie's own coding, so `data/` is not in it; CI reads the key from the private bucket at `reference/8WR QEX Combined.xlsx` with repository storage credentials, and the first CI run reproduced the local figures (305 of 325 estimates, 284 of 305 standard errors, 589 of 630). Without those credentials it reports a skip with a notice.
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
- **`evaluation/table_coverage.py` reads every results table and reports the estimate-shaped cells with no stored row on the same page.** It needs no hand-typed key, calls no model, and is the check that finds dropped cells after an ingestion batch. On paper 122182716 it reported 32 of 43 cells unstored on page 13 before the column views. In CI it read 16,934 cells and 5,609 unstored before the cell test was anchored to whole cells, which had counted labels such as 'Panel A. Endline 1 (18 months)'; the corrected count is 12,889 cells and 4,250 unstored. \evaluation/coverage_triage.py\ classifies them, and on the six re-extracted papers 419 of 491 cells remain unexplained with genuine samples, so coverage is a real deficit and the next thing worth work.
- **A row label with a units note was dropped as a non-outcome.** `is_non_outcome_label` matched its cues anywhere in the label, so `Per capita income (BDT constant price)` was dropped for the cue "constant", and paper 122182716's `936` with it. Cues are matched against the label with parenthetical units removed, in the same normalised form as the cue, which also restored `F-statistic` once hyphens were normalised.

### Measured
Against the hand-typed key, every study that has a document is scored: 43 of 43 studies and 854 of 854 values,
which is 442 of 442 estimates and 412 of 412 standard errors, one of them at the precision the paper printed.
The key itself carried seven errors, each checked against its paper and corrected in the workbook and in the
copy the gate reads, so `evaluation/key_errata.json` is empty and the mechanism remains for future corrections.
Paper 121328483 was restored from 0 of 13 to 13 of 13, and paper 121766336's 36 values came from a three-page
companion note that carries the two tables its brief cites; both documents are in the collection.

Coverage of everything the key does not cover is measured by estimate-shaped cells with no stored row: 1,914
unstored across 98 documents, 56 of them unexplained after the triage names the tables of means, balance and
attrition sheets, covariate rows, appendix pages, test p-values and subgroup differences. The real gap is 53
cells in 18 documents, down from 4,231 and 1,905 when the check was written.

The recall gate runs weekly and on changes, reads the key from private storage, and fails when the matched
count falls below `evaluation/results/recall_baseline.json`. The reader is deployed to the Modal app the API
calls, so new uploads use the current pipeline.

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


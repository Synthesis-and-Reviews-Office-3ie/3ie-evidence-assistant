# Normalisation of table results

Status: design note, 13 November 2026. This scopes the work behind N6 in [ROADMAP.md](ROADMAP.md) and the meta-analysis step in [RAG_PIPELINE_PLAN.md](RAG_PIPELINE_PLAN.md). It is a plan, not an implementation.

## The gap, measured

`src/extraction/table_estimates.py` reads one table with a model, then parses the cells in tested code. It records the literal cell text, which is the right foundation. What it does not do is produce a normalised, meta-analysis-ready record. Across the 10,014 rows in `extraction_pipeline/outputs/*/extracted_data.csv` (97 studies), the field coverage is:

| Field | Rows with a value | Share |
|---|---|---|
| `coefficient` | 10,014 | 100% |
| `literal_cell_text` | 10,014 | 100% |
| `standard_error` | 5,908 | 59% |
| `p_value_text` | 3,204 | 32% |
| `significance` | 2,804 | 28% |
| `sample_size` | 701 | 7% |
| `ci_lower` | 0 | 0% |
| `t_statistic` | 0 | 0% |
| `effect_size_assumption` | 0 | 0% |

So the estimate and its provenance are reliable, and everything needed to standardise it is mostly missing. The significance values are only stars (`***` 1,793, `**` 504, `*` 451) or the words "significant" (9) and "not significant" (3). The p-value text is either derived from stars (`p<0.001` 1,793, `p<0.01` 509, `p<0.05` 455) or a raw value, sometimes messy (`[0.000]`, `1.0`, `0.0`, `NS`).

## Data available

- **Our corpus.** `extraction_pipeline/outputs/full_corpus_for_validation.csv` (28 columns) and the per-study `extracted_data.csv` files (10,014 rows in total), which have the richer 43-column schema including `literal_cell_text`, `p_value_text`, `t_statistic`, `n_clusters`, `cohens_d`, `effect_variance`. Also `results_tables_*.csv`, which classifies tables and records `has_stars`, `has_se`, `has_pvalue`, `rows`, `cols`, `section`, `is_continuation`. That is most of a layout taxonomy already.
- **The human key.** `data/8WR QEX Combined.xlsx` (443 rows, 125 columns) is a full meta-analysis sheet: `Coeff reg`, `SE reg`, `Tstat reg`, `CI_LB reg`, `CI_UP reg`, `P value exact`, cluster and N counts, `# periods`, and the standardised outcomes `d`, `yi`, `var(d)`, `vi`, `se(g)` with a `Formula Used` code (5 in 142 rows, 6 in 300). This is the target schema, and it is the ground truth for normalisation.
- **`data/8 week SR OM Combined.xlsx`** (19 columns) is an outcome-mapping sheet: which outcome to extract and where (page, table, row, column). Use it to pick outcomes, not to normalise numbers.
- **8w-sr OM_QEX v2.** `pipelines/8w-sr/OM_QEX/om_qex_extraction_v2/` (outside this repo) writes `effect_size`, `ci_lower`, `ci_upper`, `p_value`, `standard_error`, `sample_size` and maps stars to p-values, with a validation phase (`phase7_qex_validation.py`) and a vision fallback (`phase5_pdf_vision.py`). Use it for conventions and as a baseline to beat.
- **TVET.** `pipelines/TVET/ground_truth_datasets/` has human table keys (`is_true_table`, `true_caption`, `true_page`, `row_labels`, `column_labels`) and outcome hand-checks whose `literal_text` is the raw printed form, for example `0.570 (0.179) {0.001;...}`. `CHECKER_INSTRUCTIONS.md` fixes the conventions: printed folio not viewer page, verbatim row and column labels, and awkward tables count. Use it to test table detection and to read the raw forms, not the numbers.

## Target record

One row per estimate, aligned to the 8WR key, with provenance kept:

| Group | Fields |
|---|---|
| Estimate | `estimate`, `se`, `t_statistic`, `p_value`, `p_text`, `stars`, `ci_low`, `ci_high`, `ci_level` |
| Design | `n_treatment`, `n_control`, `n_total`, `n_clusters`, `n_periods`, `control_mean`, `control_sd` |
| Standardised | `effect_size_assumption`, `d`, `var_d`, `yi`, `vi`, `se_g`, `formula_used` |
| Identity | `outcome_name`, `outcome_category`, `treatment_arm`, `subgroup`, `is_main_effect`, `is_subgroup`, `is_spillover`, `is_cost`, `is_mechanism`, `reverse_sign` |
| Provenance | `literal_cell_text`, `table_number`, `table_caption`, `page`, `row_label`, `column_label`, `study_id` |

## Taxonomy of presentation variants

Each variant needs a detector, a parser, and a test. Real forms from the corpus:

1. **Coefficient and SE in one cell.** `0.15*** (0.05)`, `356.9** (152.5)`, and the concatenated `3.55***1.132` where the SE lost its separator. Parse the number before the stars as the estimate and the parenthesised or trailing number as the SE, then treat the pair as suspect when no separator exists and record it.
2. **Stars.** `***`, `**`, `*`, `†`, `ns`, `NS`, "significant", "not significant". Map to p-bounds, never to a point p (`***` to p<0.001, `**` to p<0.01, `*` to p<0.05, `†` to p<0.10), and keep `stars` as given.
3. **Exact p.** `0.010`, `[0.000]`, `<0.001`, `p=0.478`. Strip brackets, treat `[0.000]` as below the print precision, and never read `1.0` or `0.0` as real p-values without a check.
4. **Confidence intervals.** Brackets `[0.07, 0.23]`, parentheses, `±`, two columns (`CI_LB`, `CI_UP`), and a separate row. Record `ci_level` when stated (95% default).
5. **Test statistics.** `t`, `z`, `F`, `chi2`, given directly or by "SE =". Derive p from the statistic and df only when df is known.
6. **Sample sizes.** Per arm, total, clusters (the 8WR key separates cluster counts from N), and periods. Do not treat a cluster count as an individual N.
7. **Scale and units.** Levels versus logs, percent versus percentage points, per-capita versus total, index versus currency, and nominal versus PPP (the 8WR key keeps these apart). Record `effect_size_assumption` so the standardisation is explicit.
8. **Sign and direction.** `reverse_sign` for outcomes where a fall is good, and the sign convention of the printed coefficient.
9. **Table layouts.** Treatments in columns, SE in the row below the coefficient, transposed, multi-panel (Panel A/B), multi-arm, subgroup rows, rotated and borderless tables. `results_tables_*.csv` already flags `has_stars`/`has_se`/`has_pvalue`, rows and columns.

## Table interpretation

Reading the structure is separate from reading the values. `src/extraction/table_structure.py` does the structure deterministically, with tests in `tests/test_table_structure.py` (10 pass):

- **Multi-page stitching.** `stitch_units` merges a table continued on the next page when the header repeats or the caption says "continued", and the pages are adjacent. The pipeline sends one Markdown item per parsed table, so this runs before extraction.
- **Grid and notes.** `parse_markdown_table` splits header, body and note lines using the Markdown separator. `parse_conventions` reads the notes for "standard errors in parentheses", "t-statistics in brackets", "95% CI" and the star map (`*** p<0.01, ** p<0.05, * p<0.1`).
- **Column roles.** `infer_columns` assigns estimate, SE, t, z, p, CI bounds, N, mean and SD from the header, the notes and a value profile, after expanding abbreviations (ATT, ATE, ITT, s.e., obs, sd, pp), so "ATT" and "confidence interval upper" both resolve.
- **Arithmetic resolution.** `resolve_consistency` labels an unlabelled numeric column when the estimate divided by it is a whole t-like ratio, which separates an SE column from a differently scaled one.
- **Confidence and warnings.** `interpret_table` returns the roles, the combined-cell flag (`0.52*** (0.12)`), the star map, a confidence and warnings, so a low-confidence table is flagged for review instead of trusted.

Deliberate limit: a small decimal column is not guessed to be a p-value from its values alone, because an SE, a coefficient and an elasticity look alike. A column stays unknown until a header, a note or the arithmetic decides it. The module interprets structure only and does not call a model.

### Coverage on the corpus

Run over the 1,617 parsed tables in the collection (`evaluation/table_structure_audit.py`, report in `evaluation/results/table_structure_audit_2026-11-14.md`), the interpreter reads 460 as results tables (28%). Of those, it finds a standard error, in a column or inside the estimate cell, for 275 (60%), and a p-value for 75 (16%); a confidence interval for only 4 (1%). It leaves 39% of the result-table columns unknown. Layouts split 1,545 statistics in columns to 72 statistics in rows.

Three layout classes were found in the data, and the third was added after the first run. Most tables put one statistic per column. A second class puts outcomes or models in the columns and `Coefficient`, `Standard error` and `Observations` in the first column as rows, which is now detected as the statistics-in-rows layout. A third class has outcomes in the columns with each cell holding `estimate*** (SE)` and no role labels at all, which raised the results-table count from 410 to 460 once detected. Spanish, Portuguese and French headers are folded and matched.

The p-value figure is low because p is usually stated once in the notes as a star map rather than in its own column; the star map is parsed (305 tables, 19%), so the value is available even when there is no p column. Closing the remaining 39% of unknown columns needs a row-label glossary (outcome labels such as `(1) Assets`) rather than more header terms.

Next: use these roles inside `table_estimates.py` before the model call, and treat a low-confidence table as a review flag rather than trusting it.

### Using TVET's table typing and row rules

TVET already solved two adjacent problems (`pipelines/TVET/pipeline/`, outside this repo): telling a results table from a descriptive one (`prompts/phase2_table_filtering.txt`), and excluding rows and columns that are not outcomes (`validation_rules.py`, `validation_rules.yaml`). `src/extraction/table_rules.py` ports both as pure functions with the provenance in its docstring: `classify_table` returns results, descriptive or unknown from the caption and the table's own notes; `is_non_outcome_label` catches Observations, R², Constant, Controls, SD, clusters and similar; `is_descriptive_column` catches columns of means and standard deviations.

Applied to the corpus, with the two fixes it exposed in our own reader:

- Results by caption: 456 tables (28%). Descriptive: 210 (13%). Unknown: 951 (59%), mostly tables with no caption.
- With the extra layouts (a row labelled "Treatment" plus a parenthesised standard-error row, and combined cells on half the rows), an estimate is now found in 521 tables (32%), and a standard error in 353 of them (68%).
- The caption and the reader disagree in two useful ways. In 81 tables the caption says descriptive while the reader read an estimate; inspection shows these are attrition and baseline-mean tables, so the reader over-reads and the caption should veto it. In 189 tables the caption says results while no estimate was read; these are the remaining misses to close.
- Non-outcome rows: 514 of the 10,014 extracted rows (5.1%) carry a non-outcome label, mostly control-group means ("Mean in pure control", 258) and "Constant" (21). An early version also flagged "Average effect of T1" because of the word "average"; that false positive is fixed.

Three behaviours were corrected by testing against the data: classification was reading the surrounding paragraphs (so a nearby "baseline" made a results table look descriptive); the word "matching" made "propensity score matching results" look like a balance table; and the short form "ATT" matched "attrition" because it was a prefix match. Classification now reads only the caption and the table's notes, "matching" and "propensity" are no longer standalone descriptive cues, and short forms must match whole words.

### Inside the table reader

`table_estimates.py` now uses both modules before and after the model call:

- Before the call it computes the table type and the inferred structure. A descriptive table with no estimate inferred is skipped without a model call, and the inferred structure is added to the prompt ("standard error is the column headed 'SE'"), so the model is told what each column is rather than guessing.
- After the call it drops rows whose label is not an outcome (Observations, R², Constant, Controls, means), and marks a table for review when the caption said descriptive but the model still returned estimates. Each table record now carries `skipped`, `non_outcome_rows` and `review`.

Next: close the remaining missed results tables, and measure the reader end to end on a few documents with the structure hint in place.

## A/B result (14 November 2026)

`evaluation/extraction_ab.py` re-extracts a sample with the current reader and scores both the rows already on disk and the new rows against the hand-typed key. Two runs: 6 studies first, then 12 studies with deduplication in place.

| | Old rows on disk | New reader |
| --- | --- | --- |
| Estimate value recall, 12 studies | 66 of 149 (44%) | 137 of 149 (92%) |
| SE value recall, 12 studies | 63 of 134 (47%) | 121 of 134 (90%) |
| Estimate value recall, first 6 studies | 51 of 84 (61%) | 84 of 84 (100%) |
| Rows, 12 studies | 1,816 | 4,688 |
| Duplicate rows removed | 0 | 93 |
| Distinct outcomes | 372 | 993 |
| Distinct outcome and arm pairs | | 3,014 |
| Descriptive tables skipped | 0 | 24 |
| Non-outcome rows dropped | 12 | 39 |

Across the 12 studies the reader parsed 388 tables, read 265 of them as results tables, skipped 24 as descriptive and flagged none for review. Recall rose from 44% to 92% for estimates and from 47% to 90% for standard errors. The two runs are not identical samples of tables, so the comparison is indicative.

The growth is not mostly duplicates. Distinct outcomes rose from 372 to 993, and exact dedupe removed only 93 rows, so the reader is genuinely finding more outcomes, not copying the same ones. Because 4,688 rows map to 3,014 outcome-and-arm pairs, about 1,674 rows repeat the same outcome and arm across specifications or tables. A per-outcome cap would cut this to about 3,014 rows, but it is not applied; every grounded row is kept.

Deduplication is now opt-in and off by default. Run over the 10,014 old rows the merge rule finds zero duplicates, so a repeated row is far more likely to be the reader emitting the same line twice than a repeat in the paper. Keeping those rows loses no real estimate; with dedupe off the 12-study run keeps the 93 it had merged, about 4,781 rows. All distinct numbers are kept, as intended.

## Production re-extraction (14 November 2026)

The collection was re-extracted with compute temporarily on Small. It processed 97 documents, parsed 1,808 tables, read 1,080 of them as results tables, kept 18,176 grounded estimates, and reported no errors. The `effect_estimates` table now holds those 18,176 rows of this source plus 7,127 rows from the earlier OM_QEX import, 25,303 in total.

Stored-row recall against the hand-typed key, over the 36 studies that map by id, is 278 of 325 estimates (86%) and 263 of 305 standard errors (86%), against 44% and 47% for the old rows. The 2.6 times growth measured in the A/B did not appear in production: the A/B counted in-memory estimates before grounding, while the writer stores grounded rows only, and skipping descriptive tables offsets the increase. The stored table is in fact a little smaller than the old one at 18,176 rows, while matching about twice as many of the hand-typed numbers. Every stored row carries an embedding. Compute can return to Micro; watch the Disk IO graph for a day.

## Image tables (14 November 2026, code only)

Paper 121766336 has no table text at all: 51 parsed items and six images, and 18 of the 47 missing hand-typed estimates come from there. `src/extraction/page_vision.py` reads those pages: it collects the pages that hold image items, renders each page to PNG with PyMuPDF, and sends the page image to the vision model with the same table task. Rows are built directly in the `effect_estimates` shape, and a cell such as `311** (119)` is split into estimate and standard error.

It is a fallback and opt-in: `scripts/extract_estimates.py --vision`. The text path runs first and stays authoritative; vision rows are added on top, capped at 12 pages per document. The cost is one vision call per image page, which for 121766336 is six. Seven tests in `tests/test_page_vision.py` cover page selection, rendering, and row building. The model call itself has not been run against the live API yet, because the network has been failing TLS handshakes.

The trigger is not only image items. Paper 121328483 is the second case: its parsed table text is a broken font mapping (`????? ?? ???????a114 a116a115`), so the text reader stored 15 nonsense rows from it and missed the 13 hand-typed index values. `looks_garbled` in `table_rules.py` detects that text, `table_units` now skips garbled tables so no garbage reaches the model, and `vision_pages` adds those pages to the image reader. Between them the two papers account for 31 of the 47 missing estimates.

### Vision result (14 November 2026)

The vision path works technically: the model returned valid JSON for every page. Two papers were tested.

- **Paper 121766336 is not the paper.** It is a 12-page policy brief. Its text contains no "income", "expenditure", "table" or "regression", and the impact paper behind the hand-typed numbers is not in the collection at all; only this brief carries the id. Its 18 missing values cannot be found in this corpus and should not be counted against the extractor. This is a provenance issue, not an extraction one.
- **Paper 121328483 is the garbled one.** Vision recovered all 13 hand-typed estimates and all 13 standard errors. The document now stores 217 rows, 16 from the one readable table and 201 from page images, replacing the 15 nonsense rows.

Stored recall after this is 291 of 325 estimates (90%) and 276 of 305 standard errors (90%). Excluding the 18 values whose paper is absent, the attainable recall is 291 of 307 (95%).

With the provenance check (`looks_like_wrong_version`), the missing-estimate audit now assigns 18 misses to "document is not the paper" and leaves 11 real misses, plus 5 rounding or sign cases. Automatic vision is now the default: `extract_and_store` reads image or garbled pages when the parsed content has no tables or some table text is garbled, and `scripts/extract_estimates.py` exposes `--vision` to force it and `--no-vision` to disable it.

### Correction: paper 121766336 is identified, and the values are in neither document (15 November 2026)

The bullet above, that "the impact paper behind the hand-typed numbers is not in the collection at all", is half right. The study paper is *How Big Does a "Big Push" Need to Be? Evidence from Randomizing Asset Transfer Size*, by Ragui Assaad, Adam Osman, William Parienté and Christine Valente. It covers the Bab Amal half-cost arm, it is 52 pages, and its tables are text rather than images.

It does not carry the hand-typed values. At published precision the paper reports half-transfer monthly income 107 (148) at 40 months (Table 1) and 384 (112) at 20 months (Table A5), monthly consumption 276 (109), livestock value 5549 (669), with observed counts near 3,247 per column. The key holds 155.4295 (121.73) at endline, 126.991 (62.267) at midline, 141.173 (66.809) and 6143.406 (798.5), on per-arm counts of 716 and 948, so it is not the paper's Table 1, Table A3, Table A5 or Table A6. A whitespace-tolerant search of the whole paper finds none of the 18 values, not even their digit tails.

Nor does the brief carry them. The corpus document is the 12-page MNAGIL policy brief, and the World Bank copy of the same PDF is the same document: same title, authors, date and page count. Its results are figures. It has no table named "Policy Brief Estimates for Primary Outcomes", which is the table the key's own `Source` column cites, and its figures print arm means (1,525, 1,799, 1,693, 1,662, 2,595, 2,880, 2,871) rather than coefficients with standard errors. A vision pass over all 12 pages returned 29 rows, all figure labels such as
livestock value 6857.9 to 12580, female employment 32 and 21, and food insecurity -0.119 and -0.123. None of the 18
values came back.

Those readings were checked by eye on 16 November and the values are right. Figures 1, 2 and 6 match, and Figure 5
holds -0.12, -0.08 and -0.119 at midline and -0.123, -0.074 and -0.119 at endline, which is the six values in the
store. The labels were missing at first: the arm and wave names sit inside the chart image, so the values arrived
under one outcome with no arm and two of them were identical. The figure reader now reads the legend and the panel
headings and returns a series in `treatment_arm` and a wave in `subgroup`, and after re-extracting the brief the six
food-insecurity values read Full cost -0.12, Half cost -0.08 and Restricted -0.119 at Midline, then -0.123, -0.074
and -0.119 at Endline, with the same labels on Figures 1 and 2. A figure-derived value can now be quoted with the
arm and wave it belongs to.

So those 18 estimates and 18 standard errors stay unrecovered, and the reason is narrower than an absent paper: the coder's source table is in neither document, and its precision, six and seven significant figures, is finer than any published table. Treat them as outside the collection for the recall denominator rather than as an extraction failure. `src/extraction/page_vision.py` grew a `VISION_PROMPT` figure reader for this shape of document, and 121058361 is its queue, so the brief is no longer the only open case.

### Where the remaining misses come from, and what runs in production (15 November 2026)

Two measurement faults made the audit read worse than the extractor is, and both are fixed. The
PostgREST endpoint returns at most 1000 rows per request whatever `limit` asks for, so
`error_report.py` and `missing_estimates_audit.py` compared large documents against their first 1000
rows: paper 121058367's `-0.049` is stored on page 130 and was reported missing. And a value printed
at coarser precision than the key, such as `2.40` against `2.404`, counted as a gap. `evaluation/stored_rows.py`
now holds both rules, `fetch_all` pages every read and `classify_miss` splits `exact`, `rounded` and
`absent`, and it compares only within half of the last decimal the stored value was printed to, so
`691.149` does not stand in for `691.179`, which is a different number.
Recall under those rules, after the wide-table and second-pass work described below, is 305 of 325
estimates (94%) and 284 of 305 standard errors (93%). The 42 missed values fall into four causes:

| Cause | Values | Evidence |
| --- | --- | --- |
| Source table not in the collection | 18 est, 18 se | 121766336, the Bab Amal brief, queued for retrieval |
| Key differs from what the paper prints | 0 est, 3 se | 122182715's 16.96 against printed 16.698, 121327988's 691.179 against 691.149, 121295641's 4.24 against 4.224 |
| Value not in the parsed text at all | 1 est | 121294795's 92.8 |
| Estimate stored for another arm, panel or specification | 2 est | 122182715's 57.645 and 192.975, where the paper prints 57.02 and 192.974 |

Two causes that this table held before are closed. Paper 122182716's 936 and 1664 were cells the wide
table read only in part, and the column views below recover both. Paper 121295229's 2.40 was in a
sentence and is now read by the second pass. Both rows are kept here because they are what the work was
measured against.

`evaluation/table_coverage.py` is the check that works without a key. It reads every results table,
lists the cells that carry an estimate, and reports those with no stored row on the same page. On the
two papers it was tried against it reports 32 of 43 cells unstored on 122182716 page 13 and 24 of 28
on page 14, which is the wide panel table the extractor reads one value from. It reads only, calls no
model, and belongs in the run after an ingestion batch.

The work that follows, in the order the evidence supports it:

1. Wide and panel tables: store one row per arm column, with the column header as the arm, so a
   seven-column table yields seven rows instead of one. This is the 122182716 gap and the likely
   cause of the several-hundred unstored cells across the collection.
2. A second pass bounded by the confirmed outcomes: re-read only the tables or pages that
   `table_coverage` flags, with the layout hint, instead of the whole document.
3. A provenance verdict for an absent source: a document with no results table and no estimate-like
   numbers is flagged, excluded from the recall denominator, and queued for retrieval with its
   level-1 id. This is 121766336 and should also cover the 16-page article whose table sits on
   journal page 479.
4. A printed-precision bucket in the report, so values the paper rounds are never counted as
   extractor gaps again.

### Wide tables are read one column at a time (15 November 2026)

A results table whose columns are separate estimates used to yield one value per row. Paper 122182716's
Table 3 has six estimate columns and one model call returned the first, so `Cash savings` came back as
278 and the `1664` beside it was never read. `split_estimate_columns` in `table_structure.py` now gives
each estimate column its own view, holding the label column, that column and its header, and the header
is passed to the model as the arm. Three shapes needed care: a grouped header such as
`(2) | Panel regression results (equation 1)` repeats across columns, so the group number is kept in the
name; a continuation table whose first row is data is named by position and that row stays in the body;
and a column whose header names a statistic, or that is nothing but parenthesised numbers, is not a view.

A wide table is still read whole as well, and `merge_reads` keeps one row per outcome and estimate value,
filling a standard error seen in either read. That makes the change additive rather than a swap: on paper
122182715 the column views alone lost a standard error that the wide read held. Between the two reads,
paper 122182716 stores 94 rows against 36 before, and both of its hand-typed values are found.

The cost is measured, not assumed. Across twelve documents, 341 tables produce 963 views, a multiplier
of 2.82, and with the wide read kept as well the multiplier is about 3.8 for the documents that contain
wide tables. Raising the threshold to three or four estimate columns changes the multiplier by little
(2.75 and 2.56), so the cost is genuinely the wide tables and not a threshold artefact.

One silent loss was found on the way. `is_non_outcome_label` matched its cues anywhere in the row label,
so `Per capita income (BDT constant price)` was dropped for containing "constant", which is the cue for a
constant term. Cues are now matched against the label with parenthetical units removed, in the same
normalised form as the cue, which also restored `F-statistic` after hyphens were normalised.

### The retrieval queue and the attainable denominator (15 November 2026)

One of the 36 mapped studies is scored against a document that is not the study. Paper 121766336 is
the 12-page Bab Amal policy brief, its results are figures, and the table the key cites is not in it.
`evaluation/retrieval_queue.py` gives every mapped document a verdict and writes the queue, keeping the
two cases apart:

- A document that is a review or a summary is not the study. Its missing values are set aside from the
  denominator and the study is queued for retrieval. That is 121766336, with 18 estimates and 18
  standard errors, and it is the only one.
- A key that cites a page the document does not have means the key used the source's own pagination.
  Papers 121294795 and 121295229 cite pages 153 and 482 of documents 19 and 16 pages long, because they
  are journal articles whose page numbers start in the journal. Their 2 missing values stay in the
  denominator, because the text may hold them, and they are checked before anything is retrieved.

Measured recall is 589 of 630 values (93%). Setting aside the summary's 36 values, attainable recall is
589 of 594 (99%), which is the figure that describes the extractor. What remains in the denominator after
the second pass is 121294795's `92.8`, which is not in the parsed text, 122182715's `57.645` and
`192.975`, where the paper prints `57.02` and `192.974`, and three standard errors that differ from the
printed values (`16.96`, `4.24`, `691.179`). The queue is written to
`evaluation/results/retrieval_queue_<date>.md`, alongside `table_coverage_<date>.md` from the coverage
check and `quality_gate_<date>.md` from the scheduled run.

### Standardised effect sizes (16 November 2026)

The control-statistics migration is applied. The note that it needed the Supabase SQL editor was wrong:
`scripts/db_migrate.py` holds a direct connection and reports what is pending, and it applied this
migration and a second one that adds `effect_size_d`, `var_d`, `hedges_g`, `var_g` and `se_g`.

The reader now captures the control mean and the control standard deviation. Each is accepted only when
its cell appears in the table as printed, compared as a run of tokens rather than a substring, because a
one-character count such as `1` appears inside almost any table. Paper 122182715 carries a control SD on
220 of its 315 rows, so the reading works.

The standardised columns are written with each row and stay null when an input is missing, and so far
they are null everywhere: `hedges_g` needs the treatment and control counts, and these tables print one
pooled "Observations" per column rather than a count per arm. Populating them needs either tables that
print per-arm counts or a document-level count read from a balance table, which is a separate piece of
work rather than a change to this arithmetic.

### Coverage: the mechanism, found and fixed (16 November 2026)

The triage sent us to paper 122182716 page 13, where 5 of 42 estimate-shaped cells had no row. Probes of
each column view showed why: the third panel column prints estimates with a t statistic in parentheses and
no significance stars (`-398 (-0.82)`, `0.03 (0.20)`), and `estimate_columns` selected a column only when
it found a starred value or a standard-error row beneath. That column was therefore never given a view,
and the wide-table read returned only the starred columns. The test now also accepts a column whose cells
are an estimate with a parenthesised statistic, and after re-extracting the paper pages 13 and 14 have no
missing cells (42 of 42, 18 of 18, 7 of 7) and the document stores 117 rows against 94.

Two false positives inflated the queue and are now classified: a table with no stars at all whose cells
are `value (se)` is a table of means (paper 121058367 page 64, 63 cells), and a row labelled `Test: T2 = T3`
carries the p-value of an equality test, not an estimate.

On the six papers re-extracted with the current reader, 484 estimate-shaped cells have no row and the
triage accounts for 481 of them: 391 belong to tables of means (no stars, `value (se)` cells), 59 are
control means, 15 are covariate coefficients, 11 sit on late appendix pages and 5 are equality-test
p-values. Three remain unexplained: one is a merged cell on page 104 of paper 121058367 whose row label
the parser did not carry, and two are attendance results in an appendix table of paper 122182715, which
are compliance measures rather than effects on a welfare outcome.

Almost all of the remainder were therefore not mistakes by the reader. The covariate rows are the shape
most easily misread as gaps: a regression table with the outcomes in the columns and covariates such as
"Child age in months", "Male child" and "Endline" down the rows produces coefficients that look exactly
like estimates and are not treatment effects. Storing them would be wrong, and the triage now names them.

Collection-wide the check counts 12,889 estimate-shaped cells and 4,231 with no stored row, of which 1,905
remain unexplained. That remainder is dominated by the 91 documents still carrying the older extraction,
which is what the full re-extraction is for. The hand-typed key stays at 305 estimates and 284 standard
errors throughout, so the coverage work is additive rather than a trade against accuracy.

### The unusual layouts, case by case (17 November 2026)

Re-reading the five largest gaps did not close them, so each was traced to its cause. Three came out of it,
and two were our own faults.

- **Our filter dropped real outcomes.** `is_non_outcome_label` carried "average" as a summary cue, so paper
  121354848's livestock table lost its "Average price" and "Average price (animals sold)" rows, nine cells in
  one table. A cue list cannot assume that a word which names a statistic never begins an outcome. The rule now
  drops only a bare mean or average, or one qualified as the control or baseline group, and keeps everything
  else; tests cover both directions.
- **The vision reader failed unless it was handed a client.** Its default client had no base URL, so a call
  without one raised `UnsupportedProtocol`. Production always passed a client, which is why nobody saw it; it
  is fixed.
- **A table that both readers refuse may be right to refuse.** Paper 121498842's page 55 is "Cuadro 17. Medias
  y diferencia de medias ... por el género del participante": means and difference of means by participant
  gender. That is a subgroup difference, not the programme's effect, and both readers declined it. The triage
  now recognises that caption, in Spanish and English, and no longer counts it as a gap.

A fourth class came out of the same tracing. A table that merges one label across several rows leaves the later rows with an empty first cell, so their values arrive without an outcome name; eight cells were lost that way. `carry_merged_labels` now fills an empty label from the row above when the row carries an estimate, and leaves a row that holds only a parenthesised standard error alone. Re-extracting the three documents with merged labels took their unexplained cells from ten to five.

A fifth class was heterogeneity tables, which put subgroups down the rows and outcomes across the columns.
The reader treated the row as the outcome, or refused the table, so effects by subgroup were lost. A structural
test now recognises the shape, a prompt paragraph explains what to do with it, and the structure hint says it
outright: the column heading is the outcome and the row label is the subgroup. A regression table whose columns
are models or coefficients is excluded, because its rows are covariates, not subgroups. After re-extracting the
papers with that shape, 21 stored rows carry a subgroup.

A sixth class was simply width. The column split stopped at eight columns, so a table with ten or eighteen
estimate columns silently lost the rest; paper 121295428's treatment-effects table has ten and paper 121294984's
has eighteen. The limit is now sixteen, and re-extracting the three such papers recovered seven cells.

After all of those, the real gap is 53 cells in 18 documents: 51 omitted from tables that were read and 2 on
pages with no stored rows, down from 296 and then 107. What is left is a list of small, distinct clusters rather
than a class: seven covariate cells in one determinants table that are correctly not stored, five in a subgroup
table the reader declines, four in a panel table whose first row has no label to carry, three in a
difference-in-differences column, three under a merged header, and single cells elsewhere. The others in the old count were already stored, or were
tables of means and balance sheets. The lesson for production is that an unusual layout is more often a table
that should not be stored than a reader failure, and the triage is where that judgement belongs.

### A deep pass over the remainder (17 November 2026)

The 296 figure was a page-level count and it overstated the gap. Comparing each remaining cell with every row
stored for the study, rather than only with the rows on its own page, changes the answer:

| Reason | Cells |
| --- | --- |
| stored elsewhere in the same document | 189 |
| stored in another document of the study | 3 |
| table read but this cell omitted | 75 |
| page has no stored rows | 29 |

So 192 of the 296 were already in the store, and 104 were a real gap. The cause of the overcount is ordinary:
a table that spans pages stores its rows under the page it starts on, so a cell on the continuation page looks
missing when only its own page is checked. The triage now keeps that as a separate bucket, `stored on another
page`, and the real figure is 107 cells, 0.8 percent of the 12,889 estimate-shaped cells, spread across 22
documents with 14 in the largest.

Those 107 are the cell-level omissions the completeness retry targets, and they are listed in
`evaluation/results/coverage_unexplained_<date>.json` with document, page, row and column. A pass over the five
largest documents would close most of them; the rest are single cells in unusual layouts.

### Deployed, and the tail measured (17 November 2026)

The reader is now deployed: `python -m modal deploy infrastructure/modal_mineru.py` created the functions and
the web endpoint the API calls, and the configured trigger URL answers a GET with 405, which is the healthy
signal that the function exists and expects a POST. From here a paper uploaded through the app is processed by
the current reader, not the one from before this week.

A sample of thirty-two of the remaining cells answered the question the count could not. They are not one
mechanism: about a third are shapes (baseline group columns, bracketed descriptive means), and about two
thirds are genuine estimates printed without significance stars, spread across twenty documents. That exposed
a gap in the completeness trigger, which compared the answer to the table's labelled rows: a call can return
every row and still leave a non-significant cell out. The trigger now counts estimate-shaped cells and asks
again whenever the answer is short of that number, and it no longer accepts 85 percent as complete.

On the three worst documents that took unexplained cells from 103 to 82, and the collection stands at 296, down
from 1,905 when the triage was first run. The remaining cells are a long tail with no single cause: the fix
rate per iteration is now about twenty cells for half an hour of work, so the honest next step is to leave them
listed in `evaluation/results/coverage_unexplained_<date>.json` and stop, rather than keep chasing.

### Reading a table to the end (17 November 2026)

The 519 unexplained cells that remained after the measurement fixes were real values, and most of them sat in
tables the reader had only partly returned. Extraction now finishes a table. When a table has at least four
labelled rows and the answer covers fewer than 85 percent of them, one more call asks for the rest and the
answers are merged, so a row cannot be doubled. The retry also fires when a table with starred cells was
called prose, since a table of stars is a table of estimates. The budget is twelve retries per document, which
bounds the cost on a long appendix.

Applied to the ten documents holding most of the remainder, unexplained cells fell from 370 to 169, and on the
collection from 519 to 317; the unstored cells fell from 2,242 to 2,120. Accuracy was unchanged at 854 of 854,
so the retry added rows without disturbing the values checked against the key.

The triage also learned three shapes it had been calling gaps: a balance column written as `2005 - Treated` or
`SUP-NSUP (2)`, including the broken-glyph form `ð2Þ` that one PDF produces, a descriptive mean printed as
`22.31 [7.450]`, and a household-characteristic row printed without stars. The same rows printed with stars are
left on the work list, because those are estimates.

What remains is 317 cells, 51 of them in one document. They are the tail of the collection: balance-shaped
tables with starred cells, merged labels, and layouts that neither the retry nor a label rule reaches. They are
listed cell by cell in `evaluation/results/coverage_unexplained_<date>.json` for review rather than chased.

### What the coverage queue actually contained (17 November 2026)

Reading the 941 unexplained cells one by one found three faults in the measurement, not in the reader.

- **A Spanish decimal was read as a large integer.** `0,84** (0,43)` was parsed as 84, so 167 cells of paper
  121498842's Spanish version looked unstored while the store held 0.84. A cell now yields both readings and
  counts as stored when either matches, which also covers the English `1,222` against the Spanish `1.222`.
- **Balance and attrition tables look like results.** Paper a72b's "Test of difference in mean characteristics
  between treatment and control groups in 2002" and 121058373's "Pooled Attrition" print starred cells that are
  pre-programme differences or survey response, not effects. The page's text now identifies them, which
  accounts for 282 cells.
- **A test statistic's p-value and a potential-outcome mean are not effects.** Rows labelled `t-test` and
  `po mean` are now named as such.

With those, the unstored count falls from 4,231 to 2,242 and the unexplained remainder from 1,905 to 519. Those
519 are not a measurement artefact: the samples are real values the reader did not store, such as Cantril ladder
effects of 0.06 and 0.14 in paper 0cb6 and food-security effects of -0.219 in paper 1a25, concentrated in about
ten documents. The next production fix is therefore in extraction, not measurement: a per-table completeness
retry that re-asks once when a results table yields clearly fewer rows than it has outcome rows, in the way the
second pass already works for whole documents.

The full list is exported to `evaluation/results/coverage_unexplained_<date>.json` with the document, page, row
label and column, so any remaining cell can be checked against its paper.

### The collection re-read (16 November 2026)

All 98 documents were re-read with the current reader, in thirteen paced batches at one document at a time
and a pause between them, which is what the instance's disk IO budget allows. Every batch completed with no
errors, and accuracy against the key stayed at 854 of 854 throughout, so the extra reading added rows without
disturbing the checked values.

Coverage improved materially. The estimate-shaped cells with no stored row fell from 4,231 to 2,510, and the
cells the triage cannot explain fell from 1,905 to 941. The rest are accounted for: 772 belong to tables of
means, 330 are covariate coefficients, 152 sit on late appendix pages, 128 are control means, 106 are
statistic cells, 75 are observation counts and 6 are equality-test p-values.

The 941 that remain are the next thing to read. They are a small enough list to work through by mechanism
rather than by document, and the triage report names each one with its page, row label and column.

### Disk IO, and a throttled re-extraction (16 November 2026)

The Supabase instance is small and its disk IO is budgeted, so the audits were written to stop re-reading
the same table. `quality_gate.py` and `retrieval_queue.py` used to query the estimates table once per study
per field, about eighty passes over the whole table on every run; they now read it once, group by document
in memory, and answer from that. The gate takes about sixteen seconds. Re-extraction is likewise paced:
`DOC_CONCURRENCY` is read from the environment, so a batch can be run one document at a time.

A gateway timeout on the insert used to lose a document's write and need a manual re-run. The write is now
retried as a unit after a thirty-second pause, and the document-level failure is logged only if the retry
also fails.

With that in place the five documents with the largest coverage gaps were re-extracted at concurrency 1:
Mallick 2013, 121498842's Spanish version, Ara 2021, 121326829 and Das 2010. Their unstored cells fell from
944 to 358, and 167 of the remaining are shapes the triage explains (statistic cells, covariate rows,
appendix pages, tables of means). Recall was unchanged at 854 of 854. The rest of the collection is the same
work in paced batches, which is what protects the IO budget.

### The last nine values (16 November 2026)

With the wider mapping in place, nine values remained: four from studies that had only just started to be
scored and five sheet cells. Each was traced, and they split into two real reading defects and seven sheet
errors.

The reading defects were both structural. A column headed "Lower Bounds - (2) - 0.25 SD" was treated as a
standard-deviation column because its header contains "SD", so paper 121058369's appendix lost five of its
seven columns and its income estimate of -29.08 with them; the header test is now anchored to a statistic
name rather than a substring. And a table that prints significance stars in the column beside the value left
cells such as "-81.6" unstarred, so the column looked empty of estimates; a value column followed by a
star-only column is now a view, and the stars are joined to the value. Re-extracting the two papers
recovered -29.08 and -81.6.

The other seven are errors in the hand-typed sheet, each confirmed by eye against the printed page:

| Study | Sheet | Printed | Nature |
| --- | --- | --- | --- |
| 121058369 | 227.52 (se) | 42.25 | the coefficient was entered in the standard-error column |
| 121295641 | 4.24 (se) | 4.224 | rounded differently |
| 121327988 | 691.179 (se) | 691.149 | one digit in the last place |
| 121498842 | 3.84 (se) | 3.87 | one digit in the last place |
| 122182715 | 57.645 | 67.645 | first digit |
| 122182715 | 192.975 | 192.974 | one digit in the last place |
| 122182715 | 16.96 (se) | 16.698 | not printed anywhere in the paper |

The corrections were first recorded rather than made: `evaluation/key_errata.json` held each sheet value,
the printed value and the evidence, and the audit applied them when it read the sheet. The data owner was
then asked, and with that agreement the seven cells were corrected in the workbook itself on 16 November,
with a dated backup beside it, so the errata file is now empty and the mechanism remains for future
corrections. The gate reports how many corrections it applies, which is zero while the file is empty.

On that basis every value the collection can support is now matched: 433 of 433 estimates, 406 of 406
standard errors, 854 of 854, across 43 of 43 mapped studies. Two studies were not scored at all, 121058359 (Misha et al. 2019) and 121058372 (Bandiera et al. 2017),
because their documents are named by author rather than by study id. `evaluation/study_documents.json`
assigns each one explicitly, with the title as evidence, and both then scored every value: the assignment
was the only thing missing. All 43 studies are now mapped and all 854 values match.

### Paper 121766336: the source was found (16 November 2026)

The 36 values that could not be reached were never missing, only undocumented. The document behind them is
a three-page companion note, "Bab Amal Policy Brief Details", which holds Table 1: Policy Brief Estimates
for Primary Outcomes (Endline) and Table 2: ... (Midline), with all 18 coefficients and all 18 standard
errors verbatim, the arms as Full-Cost Unrestricted, Full cost Restricted and Half cost, and the p-values
and sample sizes. It contains every value the sheet records and nothing in the brief or the working paper
did.

The note was added to the collection as `details121766336_Bab_Amal_Policy_Brief_Details`, parsed and
extracted like any other document (39 rows), and all 36 values now match. The earlier conclusion in this
record, that the values sat outside the collection and should be set aside, is superseded: they were in a
document we did not hold, and asking for it was the right fix.

That exposed a second problem. The evaluation mapped a study only when exactly one filename contained its
id, which worked while every study had one document and breaks the moment a study has two. A study now maps
to every document whose filename carries its id, and a value counts when any of those documents stores it.
Mapped studies rose from 36 to 41 of 43, and the denominator from 630 to 839 values, because studies that
had been silently excluded are now scored. That is a definition change as well as a recovery, and the
figures before and after it are not comparable.

On that wider set, recall is 429 of 433 estimates (99%) and 401 of 406 standard errors (99%), 830 of 839 in
total. Nine values remain. Five are the sheet cells listed in `evaluation/results/key_discrepancies_2026-11-16.md`.
Four belong to two studies that the wider mapping has just started to score, 121058369 (-29.08 and 227.52)
and 122182711 (-81.6), plus 121498842's standard error 3.84. Those four are a coverage question of the
ordinary kind and are the next thing to look at.

### Standardised effect sizes: the arithmetic is ready, the inputs are not (17 November 2026)

`effect_sizes.py` computes `d`, `var(d)`, `g`, `var(g)` and `se(g)`, and the columns exist. It needs four inputs
per row: the estimate, its standard error, the outcome's standard deviation in the control group, and both arm
counts. The reader now captures all four where a paper prints them:

- a per-column observation count, taken from an Observations or N row, but only when the counts differ by
  column, so a pooled count repeated across columns is never mistaken for a per-arm one;
- the control column's count from its header, because a control column usually carries no stars and so is never
  one of the estimate views;
- the two arm counts joined per page and outcome, since a column view holds one arm;
- the control standard deviation joined to an effect row by the outcome's name within the document, exact match
  only, because a loose match could attach one outcome's deviation to another's estimate.

Re-extracting the seventeen documents that print a control deviation produced 4,125 control deviations, 2,639
treated counts and 281 control counts, and 62 rows where all four inputs meet: 54 in paper 121058356 and 8 in
121294841. That is the finding. Published tables rarely print the control deviation and a per-arm count for the
same outcome, and the join between a descriptive table and an effect table has to survive a change of outcome
name. The 8WR coder had the authors' output, which is why its key carries full precision.

So standardised effects are produced wherever the inputs exist and will accumulate from new uploads, but they
cannot be reconstructed at scale from the papers in this collection. Reproducing the key's `d`, `g` and `yi`
needs that output, not a better reader.

### Coefficients, standard errors, intervals and p-values (17 November 2026)

The second cell of a results table can hold a standard error, a t statistic, a confidence interval or a
p-value, and telling them apart is what the store depends on. Of the 30,801 stored rows, 23,357 carry a standard
error, 218 carry a confidence interval, and 7,226 carry neither, which is a t statistic or nothing printed. The
non-negative standard errors and the intervals that contain their own estimate are the checks that catch a
misread cell.

Three faults surfaced. Thirty-seven standard errors were zero or negative, which cannot be a standard error and
implies infinite precision. Twenty-seven intervals did not contain the estimate printed beside them, so the
bracket and the number came from different places. Twenty-nine p-values contradicted the significance stars on
the same estimate, which means the p-value belonged to another test.

The reader now drops a zero standard error, an interval that excludes its own estimate, and a p-value that
contradicts its stars; each has a test. The rows already stored under the old rule were cleared, and the checks
now read 218 of 218 intervals containing their estimate, 23,357 of 23,357 standard errors positive, and 243 of
243 p-values consistent with their stars. The hand-typed key independently confirms the classification where it
matters: all 412 of its standard errors match.

### Precision: what a sample showed and what the fixes changed (17 November 2026)

Recall against the key says the values a person coded are found; it says nothing about the rows the key does not
cover. To get a sense of that, I read fifty stored rows across three papers with few tables, by eye against
their printed tables.

Of the fifty, every value was a number the paper prints, so no coefficient or standard error was misread. But
only 38 were treatment effects: twelve were levels, such as "88% of female respondents use a VESA" from a paper
with no tables, where the prose reader accepted a share as an estimate. Six were duplicates, because a column
view called a row "(1) Indicator if household owns sheep" and the whole-table read called it "Indicator if
household owns sheep". And the arm field was wrong on 28 rows, because a table whose only body row is
"Treatment" and whose columns are outcomes had its columns read as arms.

Three fixes followed. The prose reader now requires a sentence to report a change, and rejects a share written
as "N% of"; a single-row table whose row names an arm is read whole rather than by column; and the merge that
combines a table's reads strips a leading column marker before comparing outcomes.

Re-extracting five small papers, three from the first sample and two new ones, and reading the result again: 53
of 54 rows are treatment effects, one duplicate remains (a hyphenated line break in the label defeats the
merge), and the arm field is still wrong where a row names the arm and the columns are outcomes, because the
model assigns the column heading as the arm even when the table is read whole.

Two measures were then taken on six more papers, 1,097 rows: value identification, meaning the stored number is
printed on the page the row names, is 1,085 of 1,097 (98.9 percent); parameter identification, meaning the stored
standard error is printed, is 819 of 819, and 819 of 1,097 rows carry one at all, because paper 82fc prints
estimates and contributions with no error and 6954's effect rows come from prose. The eleven values not found on
their page are prose rows whose quote also appears on another page, so the page attribution is the fault rather
than the value. Paper 82fc prints the same estimates in two tables and both are stored, which is faithful to the
paper but would double-count in a meta-analysis.

Recall is unchanged at 854 of 854. The fixes apply where a document is re-extracted; the other 93 documents
still carry the prose levels and marker duplicates the sample found, and cleaning them means re-extracting with
`prune`, which is a supervised run rather than a routine one.

### Two-level accuracy, measured by address (18 November 2026)

The checker could only see a third of the rows because it found cells by name: the model records a column as
"Half cost" while the paper prints "1-year results - T1-C", and in 2,394 rows no heading matched. Naming is not
address, and a check that depends on names measures the names.

The reader now returns the address of the cell it read: the row number, the column number, and which view of a
wide table it was reading. The address is accepted only when the printed cell holds the reported number with the
same sign, and once accepted the printed token becomes the value, so a copy that dropped a minus or reformatted a
number cannot reach the store.

Measured on the six papers, 4,777 rows:

| | Result |
| --- | --- |
| Rows carrying an address | 4,431 (92%) |
| Value matches the addressed cell | 4,430 of 4,431 (100.0%) |
| Parameter matches the addressed cell | 3,279 of 3,303 (99.3%) |
| Parameter printed but not stored | 14 |

The rows without an address are the residual: 387 rows where the model did not return a usable number or the
printed cell did not hold its figure. They are reported as unaddressed, not scored.

`repair_addresses` makes one more call per affected table view, capped at four views and five rows each,
asking only where the cells sit. Every answer is validated against the table: the coefficient cell must hold
the coefficient and the error cell must be adjacent and hold a number. It raised address coverage from 90 to
92 percent and parameters from 98.9 to 99.3 percent without changing a value.

The parameter printed beside a coefficient now wins when it sits in the same cell: the number in parentheses
immediately after the coefficient is taken, so "0.076 (0.156) 0.410" pairs 0.076 with 0.156. A blanket rule that
dropped the model's parameter whenever a cell held more than one number was tried and rejected on measurement: it
also discarded parameters printed in the row beneath, and took the parameter rate from 98.1 to 93.3 percent.

The same address was asked for the standard error, and that was tried and rejected on measurement too. The model
points at the row beneath while the error is in the same cell, so letting the address drive the value corrupted
pairs that were right; the address is now stored and used only to check the parameter, never to set it. What
survives is a different class of error, and it is a reading error rather than a copying one: in a table whose
cells hold two numbers, such as "(0.706) 1.109", the model occasionally pairs a coefficient with the standard
error of the neighbouring estimate, 24 rows of 3,303. That is the next thing to fix, and it is now visible per row.

### Arithmetic checks on every stored row (18 November 2026)

A row's numbers constrain each other, so a row can be checked without going back to the page. `src/extraction/consistency.py`
tests four relations: t equals the coefficient over its standard error; the p-value follows from t; the confidence
interval is centred on the coefficient at a plausible multiple of the standard error; and the arm counts are
positive and no larger than a printed total.

Run over the collection, 29,939 rows, 29,738 are consistent (99.3 percent). The 201 that fail all fail the count
check: the stored sample size is smaller than the sum of the arm counts, which means one of the two was misread.
The t, p and interval checks found nothing, because those fields are still sparse: t was only added to the store
today and an interval is stored on a few hundred rows.

The check runs at write time. A row that fails drops the field that cannot be trusted and keeps the reason in
`quality_flags`, because a missing value is recoverable and a wrong one silently biases a pooled estimate. The
201 existing failures sit in documents not yet re-read; they disappear as those documents pass through the reader.

## Coverage and accuracy: where the work stands (17 November 2026)

This is the short account of a long week, for a reader who does not want the dated entries below.

**Accuracy against the hand-typed key.** All 43 studies are mapped and all 854 values match: 442 of 442
estimates and 412 of 412 standard errors, one of them at the precision the paper printed rather than exactly.
The key itself had seven errors, verified against the papers and corrected in the workbook and in the copy the
CI gate reads; `evaluation/key_errata.json` is empty and the mechanism remains for future corrections.

**Coverage of everything else.** The hand-typed key covers 854 numbers; the collection prints far more. A
coverage check reads every table, lists the cells that carry an estimate (a value with stars or a bracketed
statistic) and compares them with the store. It began at 4,231 unstored cells and 1,905 it could not explain.
It is now 1,914 unstored and 56 unexplained, a real gap of 53: 51 cells omitted from tables that were read and
2 on pages that were not.

**What was actually wrong, in six mechanisms.** Broken font mapping in three papers, repaired by reading the page
image; wide tables read in part, now one view per estimate column up to sixteen; estimate columns with a
t-statistic and no stars, never selected; significance stars printed in the column beside the value; merged row
labels leaving later rows nameless; and heterogeneity tables whose rows are subgroups and columns outcomes. Each
has a test. Three measurement faults sat on top: a Spanish decimal read as an integer, a page-level comparison
that counted values stored on another page as missing, and a filter that dropped outcomes beginning "Average".

**What the queue still calls unexplained, and why it is left.** Seven cells in a determinants table are
covariates and should not be stored. Five sit in one subgroup table the reader declines. Four are a panel
table's first row, which has no label above it to carry. Three are a difference-in-differences column, three sit
under a merged multi-row header, and the rest are singles. Two of those are worth fixing because they recur: the
DiD column view and the first-row label. The others are correct exclusions or need the page image rather than the
text, and are listed cell by cell in `evaluation/results/coverage_unexplained_<date>.json`.

**How it runs.** The recall gate runs weekly and on changes, from `.github/workflows/quality-gate.yml`, and fails
when the matched count falls below `evaluation/results/recall_baseline.json`. The audits read the estimates table
once per run, not once per study. Re-extraction runs in paced batches at one document at a time for the disk IO
budget. The reader is deployed to the Modal app the API calls, so new uploads use it.

### Every reachable value is now found (16 November 2026)

Two faults kept five values out of the match, and both were ours rather than the papers'.

The hand-typed sheet writes one coefficient as `−92.8` with a typographic minus. Every parser read
that as `+92.8`, searched for the wrong sign and reported the value missing, which it was not: the paper
prints it and the store holds it. The four number parsers now normalise the typographic dashes first, and
paper 121294795's value matches. That is one value, but it is the kind of thing that would have kept
recurring.

The other four are genuine differences in the sheet. `evaluation/results/key_discrepancies_2026-11-16.md`
lists them with the printed value beside each: two are one digit out in the last decimal place, one is a
rounded standard error, one is a standard error that does not appear in the paper, and one is a
coefficient that belongs to a different cell. In every case the printed value is what the store holds, so
these are corrections for the data owner, not an extraction problem. With them corrected, recall would be
307 of 325 estimates and 287 of 305 standard errors, which leaves only the 36 values for 121766336 whose
source table is not in any public copy of the work.

### A re-run cannot lose a value (16 November 2026)

Extraction replaced a document's rows, so recall depended on a stochastic read: a run that failed to
reproduce a row lost it, and the weekly gate caught exactly that, at 304 values matched one day and 303
the next.

The first attempt was to stop replacing: `row_key`, an md5 of source, page, outcome, arm, subgroup and the
value, with a unique index and an upsert by that key. It cannot lose a row, but it grows without bound,
because the model words an outcome differently between runs. The key now normalises a leading table or
panel marker and a trailing column number, and even so paper 121295229 went from 260 to 379 rows in a
single run, nine copies of one value. That was measured and the approach abandoned for storage.

What ships is replacement plus a value guard. The identity for the guard is the page and the value, not
the label: after a run, any stored row whose page and value the new run did not produce is carried
forward, so a replacement cannot reduce the set of values a document has. `prune=True`, or
`--prune` on the script, replaces without carrying forward, which is the deliberate clean-up after a
change. The stable `row_key` stays for the unique index, and an identity repeated within one run is
written once so the index cannot reject a batch. Measured on the paper that lost a value: a prune left
169 rows, a normal run produced 180 with 1 carried forward, and the gate holds at 305 estimates and 284
standard errors.

### The second pass, and the check that runs on a schedule (15 November 2026)

The first pass reads every table once and can still miss a value: a column not followed, a number
printed in a sentence rather than in a cell, a table the classifier skipped. `src/extraction/second_pass.py`
re-reads only the units that mention an outcome the paper claims and no stored row carries, using the
outcome confirmation that already runs, with a cap of eight tables and eight text spans per document.
The cap is per kind on purpose: the first version shared one budget, so a paper whose missing outcome
appeared in eight tables spent all of it on tables and read a single sentence, which is where the value
happened to be. A sentence is selected on the outcome's distinctive word, because the confirmation calls
it "Consumption (per capita) treatment effect at years seven and ten" and the sentence says
"consumption". Rows from the second pass merge with the first by outcome, arm and estimate, and a repeat
fills a gap rather than adding a row.

On the four papers that had misses, the second pass read 32 units and added 71 rows. It recovered one
hand-typed value, 121295229's 2.404, which the document prints as 2.40 in a sentence. The rest of the
remaining misses are not coverage: 122182715 prints 57.02 against a key of 57.645 and 192.974 against
192.975, 121294795's 92.8 is not in the text, and 121327988's 691.179 and 121295641's 4.24 differ from
the printed 691.149 and 4.224. Recall is 305 of 325 estimates (94%) and 284 of 305 standard errors (93%).

`evaluation/quality_gate.py` is the check that now runs weekly and on changes to the extraction or
evaluation path, from `.github/workflows/quality-gate.yml`. It reads the database and the key, takes
about a minute, calls no model, and fails the run when the matched count falls below
`evaluation/results/recall_baseline.json`; `--update-baseline` rewrites that file and is a deliberate
act. The same workflow lists tables whose cells have no stored row, for information. That is the answer
to how the earlier reclassification could halve a paper's stored rows without anyone noticing: it could
not, once this ran.

The repository is public and the hand-typed key is 3ie's own coding, so `data/` is not in it. The key is
kept in the private bucket the app already uses, at `reference/8WR QEX Combined.xlsx`, and the workflow
reads it with repository storage credentials; the gate therefore compares in CI, and the first run there
reproduced the local figures exactly (305 of 325 estimates, 284 of 305 standard errors, 589 of 630). If
those credentials are absent the gate reports a skip with a notice rather than failing on a file it must
not have.

The coverage check reads all 97 documents in CI and, with the cell test anchored to whole cells, counts
12,889 estimate-shaped cells, of which 4,250 have no stored row on the same page. `evaluation/coverage_triage.py`
classifies them: observation counts, control means, statistic cells and appendix pages account for some,
and the rest are unexplained. On the six papers re-extracted with the current reader the triage leaves
419 of 491 cells unexplained, and a sample of those is genuine: cells such as `-398 (-0.82)` and
`0.03 (0.20)` in paper 122182716 that no row carries. Coverage is therefore a real deficit and not only a
measurement artefact, and it is the next thing worth work; the hand-typed key cannot see it, because it
contains 325 values and the collection has thousands.

Two later faults were found by making these checks run for real. A batch insert mixed rows from the table,
vision and prose readers with different shapes and failed with `PGRST102 All object keys must match`, so
rows are now normalised to one key set before writing; the same message had been blocking study cards,
whose writer dropped null fields per row, and grouping rows of equal shape fixed it (98 cards now build).

### Collection vision scan (14 November 2026)

`evaluation/vision_scan.py` reads the 97 cached content lists and flags documents whose text path cannot be trusted. Six need vision: three with garbled tables (121327988, 121328483 and the Emran 2012 paper) and three with no parsed tables (the Egypt policy brief, the Malawi overview, and 121058361). A 2024 reflection, "Can Poverty Graduation Programs Truly Free the Poor? Reflections on International and Regional Experiences", is skipped as a review by `looks_like_review`, because a review has no results of its own.

The two no-table documents already identified as the wrong version of a study (the Egypt policy brief and the Malawi overview) were not re-extracted. The third, 121058361, is a SPIR learning brief whose results are in 24 figures and in the prose, with no tables at all. That is a figure and prose extraction job, not a table-reading one, and its confirmation flags (poultry, savings, credit, outside labour) are the queue for it. So table extraction is now close to its ceiling for this collection.

Recall is 299 of 325 (92%) and 283 of 305 (93%), which is 97% of the attainable 307. Two bugs surfaced in this pass. Paper 121330141's difference-in-difference table was skipped as descriptive because the table has a "Baseline" column; classification now reads the caption, not the header. Paper 121475285's Table 2 was not read because its layout was not described: outcomes across the columns (Tot, logTot, Food), treatment arms down the first column, and each arm's standard error in the row beneath. The prompt and the structure hint now describe that layout, which recovered 5 estimates and 5 standard errors.

Of the 30 remaining misses: 18 belong to the absent paper, 5 are rounding or sign, and 3 are real: a near value in 121295229 (2.404 against 2.471), income in 121305126 (-0.59 against -0.60, and its standard error), and per-capita income in 122182716 (936 against 746, likely another wave or arm). `evaluation/error_report.py` writes every remaining error with its nearest stored value.

## Parser failure and garbled pages (14 November 2026)

Some PDFs come through the parser with a broken font mapping: letters become `?` and codes such as `a114`. Paper 121328483 is the case, and its tables were unusable as text. Three pieces now handle it:

- `looks_garbled` in `table_rules.py` detects it, and the text path skips garbled tables, so garbage is never sent to the model.
- The extraction-time vision reader renders those pages and reads the table image; it recovered 13 of 13 hand-typed values on that paper.
- `transcribe_garbled_pages` in `page_vision.py` replaces a garbled page with one clean Markdown transcription, for the retrieval side. It is tested with a fake transcriber; its live call is the same vision path already proven on the page images.

For production, in order:

1. Wire `transcribe_garbled_pages` into the parse step before the markdown or content list is written, so new uploads get clean text, and pass the cleaned content to extraction as well. Then a garbled page never reaches the chunk index.
2. Re-index the collection once to rebuild chunks for the affected pages.
3. The durable fix is a parser upgrade, MinerU 3.x or the Docling union (roadmap S4 and TVET T4), which should remove the broken mapping at the source. The transcription is the mitigation until then.

One more provenance check is needed. StudyID 121766336 maps to a policy brief, not the impact paper, so the recall audit counts 18 values as misses although the paper is absent. A document with no table, no "regression" and a short text is probably the wrong version of a study, and the audit should say so rather than score it as an extraction failure.

## Outcome confirmation and figures (14 November 2026)

A few papers report their headline result in a figure rather than a table, and a table reading can miss the outcome a paper itself leads with. Two additions:

- The vision prompt now also reads values printed on a figure (data labels, callouts such as `0.12***` or `[0.05, 0.19]`), and never estimates from axis positions, bar heights or line positions. A plot with printed values is treated like a table; a bare plot returns "no table".
- `outcome_confirmation.py` asks the paper's text which outcomes it reports as primary and secondary, with a quote for each, and compares that list with the extracted outcome names. A confirmed outcome with no matching extracted name is logged as a review flag. It runs for documents that go through vision, so the extra call stays bounded to the risky documents.

## Prose estimates (14 November 2026)

Paper 121058361 is a SPIR learning brief with 24 figures and no tables; its results are in sentences ("poultry ownership rose by 4 percentage points"). `prose_estimates.py` reads the text once for documents with no tables and keeps only estimates whose quoted sentence appears in the text, so a fabricated sentence cannot survive. Rows are marked with an `extraction_method` ending in "prose", and their unit (percent, percentage points, count) is kept in `literal_text`, because there is no unit column.

On that brief it produced 6 to 7 rows across two runs. The confirmation step now also matches a longer extracted label containing the confirmed outcome ("Poultry ownership" inside "Poultry ownership among cash transfer recipients"), which reduced its flags from 5 to 3. Confirmation now runs for any risky document (one that used vision or prose), with its own client, instead of only inside the vision path.

Caveats: prose numbers usually have no standard error, and a percent change, a percentage-point change and a count are not comparable. Downstream use should treat prose rows as lower confidence than table rows, and no standardised effect should be computed from them until the unit is read.

## Derivation and consistency rules

- `t = estimate / se`; `se` from a CI as `(high - low) / (2 * z)` at the stated level; `p` from `t` and df when df is known; stars to a p-bound otherwise.
- `d` from `estimate` and `control_sd` when the outcome is continuous and the scale is known; percent change to log points when the outcome is a share.
- `yi`, `var_d`, `vi`, `se_g` from `d` and the sample sizes per the 8WR `Formula Used` codes (5 and 6), so a row is reproducible against the human sheet.
- Multi-arm tables split into pairwise contrasts against the stated control. Repeated outcomes across tables deduplicate on study, outcome, arm and estimate, keeping the table the text cites. Every derivation writes what it used, so a row can be traced from `literal_cell_text` to `yi`.

## Validation

The human key makes this measurable without new coding: `data/8WR QEX Combined.xlsx` for numbers, and the TVET hand-checks for raw forms. Report per-field precision and recall (estimate, SE, CI, p, N, d, yi) against the key, with a confusion matrix per variant. Run three arms on the same rows: current `table_estimates.py`, OM_QEX v2, and the new normaliser, and keep the one that wins per field. Gate changes on the key the way `evaluation/gate.py` gates answers.

## P0 result (13 November 2026)

`evaluation/normalisation_audit.py` answers the first question with data already on disk, and the answer changes the plan. Where the printed cell contains a standard error, stars, a confidence interval or a p-value, the parser captures it: 0 unparsed of 2,126 parenthesised SEs, 2,748 star rows, 7 interval pairs and 3,196 p-value texts. The parse layer is not the bottleneck.

The bottleneck is extraction coverage and alignment. On the 41 studies that join to the human key by numeric id, our extraction contains the human estimate value (exact match) for 168 of 433 rows (39%) and the SE for 154 of 406 (38%). Matching rows on outcome and arm is unreliable, at 64 of 433, so the per-field agreement numbers (estimate 12 of 64, SE 10 of 52, p 2 of 41, N 6 of 23) mix extraction error with label noise and should not be read as accuracy yet.

So P1 (deterministic parsers) is low value now. The next move is to diagnose the 61% value-recall gap: rounding and units (0.15 against 0.1503), sign conventions, or estimates that sit in tables we did not read. Improving row alignment on study, outcome and arm is the other half, because without it per-field accuracy cannot be measured.

## Standardised effect sizes (14 November 2026)

`effect_sizes.py` computes the pooling fields: `d = estimate / control_sd`, `var(d) = (se / control_sd)^2`, `g = J * d` with `J = 1 - 3 / (4 df - 1)` and `df = n_treatment + n_control - 2`, `var(g) = J^2 * var(d)`, `se(g) = sqrt(var(g))`, and `yi`/`vi` are `g`/`var(g)` for a single study. It returns nothing when `control_sd` or the two sample sizes are missing, rather than guessing.

Two limits. The 8WR sheet stores a `Formula Used` code (5 and 6) whose definitions are not in the repository, so the module writes a descriptive formula name instead; reproducing those codes needs the definitions. More importantly, the inputs are the current gap: extraction stores `sample_size` but not `control_sd` or the per-arm counts, so most stored rows cannot be standardised yet. The human key has those columns, so reading the control mean and standard deviation and the per-arm counts is the prerequisite. Four tests cover the arithmetic and the missing-input cases.

## Status (14 November 2026)

The extraction pipeline now has, in order: text parsing and grounding; table structure interpretation (columns, rows, notes, abbreviations, arithmetic); table typing (results, descriptive, reviews); non-outcome and descriptive-column filters; multi-page stitching; vision for image pages, garbled text and values printed on figures; prose extraction for documents with no tables; outcome confirmation against the paper text; provenance checks for a wrong version or a review; and layout hints for statistics in rows, outcomes in columns, and repeated method blocks.

Measured against the hand-typed key on 36 studies:

- 300 of 325 estimates (92%) and 284 of 305 standard errors (93%).
- 97% of the attainable 307, because 18 values belong to a paper that is not in the collection.
- Remaining: 18 absent paper, 5 formatting (rounding or sign), and 2 real (121295229, 122182716), where the key's value is not in the paper's text (likely another column or survey wave).

Known limits:

- The arm year is lost on the multi-year table in 121475285 ("TUP" instead of "TUP*2014").
- Prose rows keep their unit in `literal_text`, not in a column, and usually have no standard error.
- The parser repair is called from `pdf_processor` before the markdown and content list are saved, best effort, and never fails a parse run. It only takes effect on the next parse, so the existing collection still needs a re-index for its garbled pages.
- Standardised effect sizes (`d`, `yi`, `var_i`, `se_g`) are implemented, but most rows lack `control_sd` and per-arm N, which extraction does not read yet; the migration `20261114000000_effect_estimates_control_stats.sql` adds the columns and still has to be applied.

Next, in order:

1. Re-index once so the parse repair reaches the retrieved chunks, then re-run the vision scan to confirm no document is still garbled. This needs the parse to run again (Modal), not only the extraction step.
2. Apply the control-stats migration, then read `control_sd` and the per-arm counts in extraction, so the standardised effects can run.
3. Reproduce the 8WR `Formula Used` codes once their definitions are known.
4. Resolve the two remaining real misses: they are key values that do not appear in the paper text, so check them against the paper rather than the extractor.


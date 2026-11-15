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

Nor does the brief carry them. The corpus document is the 12-page MNAGIL policy brief, and the World Bank copy of the same PDF is the same document: same title, authors, date and page count. Its results are figures. It has no table named "Policy Brief Estimates for Primary Outcomes", which is the table the key's own `Source` column cites, and its figures print arm means (1,525, 1,799, 1,693, 1,662, 2,595, 2,880, 2,871) rather than coefficients with standard errors. A vision pass over all 12 pages returned 27 rows, all figure labels such as livestock value 6857.9 to 12580, female employment 32 and 21, and food insecurity -0.119 and -0.123. None of the 18 values came back.

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
Recall under those rules, after the wide-table and second-pass work described below, is 304 of 325
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

Measured recall is 588 of 630 values (93%). Setting aside the summary's 36 values, attainable recall is
588 of 594 (99%), which is the figure that describes the extractor. What remains in the denominator after
the second pass is 121294795's `92.8`, which is not in the parsed text, 122182715's `57.645` and
`192.975`, where the paper prints `57.02` and `192.974`, and three standard errors that differ from the
printed values (`16.96`, `4.24`, `691.179`). The queue is written to
`evaluation/results/retrieval_queue_<date>.md`, alongside `table_coverage_<date>.md` from the coverage
check and `quality_gate_<date>.md` from the scheduled run.

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
the printed 691.149 and 4.224. Recall is 304 of 325 estimates (94%) and 284 of 305 standard errors (93%).

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
reproduced the local figures exactly (304 of 325 estimates, 284 of 305 standard errors, 588 of 630). If
those credentials are absent the gate reports a skip with a notice rather than failing on a file it must
not have.

The coverage step reads all 97 documents in CI and reports 16,934 estimate-shaped cells, of which 5,609
have no stored row on the same page. That number is not a defect count: control means, appendix
replications and cells of tables the reader was never meant to store all qualify as estimate-shaped. It
is a review queue, and it needs calibration against a sample before it drives work. What it did establish
is that the check runs on the real collection, not only on the machine where it was written.

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

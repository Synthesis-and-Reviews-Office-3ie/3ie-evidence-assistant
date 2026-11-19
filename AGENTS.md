# AGENTS.md: devchat

## PDF processing pipeline: production requirements

The PDF pipeline (`infrastructure/modal_lib/`, `src/extraction/`) is a **production target**, not a
prototype. Changes to parsing, extraction or evaluation must satisfy these requirements.

- **Multi-parser, not single-parser.** Parse every document with Docling and MinerU, then reconcile the
  two into one canonical document. A single parser is a fallback, never the design. The reference
  designs are TVET's `PLAN_pdf_parsing_and_outcome_listing.md` (engines to a canonical document per
  study) and sr-platform's parser service plus dual-extraction reconciliation (M7/M8).
- **Consider every table.** Classify each table as results or descriptive before dropping anything.
  Do not discard tables by parser shape.
- **Validate every estimate against its cell**, and keep provenance: page, table, row, column, arm.
- **Reconcile and deduplicate** across parsers and across repeated rows (TVET inventory union;
  sr-platform conflict-detect/resolve).
- **Canonical outcome taxonomy per corpus.** TVET's `config/taxonomy.yaml` with `normalise_outcomes.py`
  is the reference implementation. Re-author the taxonomy for each corpus; reusing another corpus's
  terms produces wrong mappings (see sr-platform `AGENTS.md`).
- **Evaluate every document of a study**, not one document per study.
- **One engine, many corpora.** The engine is shared across TVET, sr-platform and devchat; only the
  corpus taxonomy, prompts and validation terms differ.

If a change makes the pipeline single-parser, skips table classification, or scores one document per
study, it is wrong for production even if it passes.

## Evaluation protocol for parser and reader comparisons

Learned from a comparison that mixed code versions and was therefore invalid.

- **One commit, one measurement.** Re-extract every source at the same git commit, with `prune=True`, so no
  row from an older run survives. Record the commit in the report. `evaluation/reextract_all.py` does this.
- **Never compare rows written at different times or by different code.** The reader
  (`src/extraction/table_estimates.py`, `store_estimates.py`) changes often and is shared by every source.
  Check each source's row `created_at` before scoring; a mix of dates means the comparison is confounded.
- **Score every document of a study**: paper, appendix, brief, translation. Not one document per study.
- **Report recall under three name rules on the same denominator**: exact name, token overlap, and canonical
  category, each requiring the value at printed precision. Canonical recall is a naming allowance, not a
  rewrite of the data, and it is not precision. State the denominator (439 categorisable hand rows).
- **Two mapping functions must agree** on which document is the mapped one for a study. The 122182711
  English/Spanish pair exposed a disagreement between `graduation_gt.pick_document` and
  `outcome_gap_audit.mapped_and_all`.
- **The union must deduplicate tables** and prefer the primary parser's render, borrowing the caption, because
  MinerU's HTML-to-Markdown row labels are weaker. Duplicate tables are what cost the union its canonical
  matches.
- **Parsing is not the binding constraint.** Canonical recall around 87% with exact-name around 40% means the
  estimates are present and the labels differ; the next work is row, column and panel selection in the reader,
  not more parser combinations.

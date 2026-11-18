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

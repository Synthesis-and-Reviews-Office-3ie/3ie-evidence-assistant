# Effect-role flag: sample check, 2026-11-20 (corrected)

## Retraction

The earlier version of this file reported "0 of 43" real effects dropped and called the result an
independent audit of a fresh sample. Both claims are withdrawn.

- The classifier was a model checking a model. Sonnet was given the same six-role rules as the reader,
  so it is a second opinion under one rule set, not independent evidence about the reader's output.
- The sample was not fresh. Of its 60 cells, several documents had already been used: `9b89a1ab05bf`,
  `b98a0422b2e2`, `e23a72cd85d8` and `20883ddebbf3` were in the held-out ten, and `0cb609fbf433`,
  `8d23199222c8`, `37ec5820d8e8` and `4a1f5e7f9586` are among the 49. The "0 of 43" figure is not
  evidence and is retracted until a page-checked audit confirms it.

## Classifier errors

The second model was wrong on cells a reader of the page would not confuse. It labelled the outcome
`Locus of Control` (`e23a72cd85d8`) and `Total number of poultry owned` (`442bb134bc3b`) as controls, and
marked `cowbull_a` (`4a1f5e7f9586`) and other outcome rows as non-effects. Any count from this classifier
carries that error rate, which is why the claim is withdrawn.

## What was actually run

- Reader model: `anthropic/claude-haiku-5.5`.
- Classifier model: `anthropic/claude-sonnet-5.5`, same six-role prompt.
- Sample: 60 stored cells across 57 documents, seed 20261120, file
  `evaluation/results/final_audit_sample_2026-11-20.csv`.
- The classifier labelled the two axes of each cell; the fail-open rule then gave a keep or drop; that
  was compared with the stored `keep_effect`.

The raw classifier output is in `evaluation/results/final_audit_2026-11-20.json`. It is retained as a
record of what was run, not as a result.

## Row count

The re-extraction covered the 49 mapped documents only. The stored total of 25,834 rows is the whole
project, which holds 94 documents:

- The 49 mapped documents hold 14,136 rows (the "≈16,500" earlier figure was the 49-document count at
  commit `5c20164`, so the two numbers are not like for like).
- The other 45 documents hold 11,698 rows from earlier runs and were not re-extracted.

So the count did not rise for the 49; the larger total is a wider document set.

## Status

The flag is stored on every row and no row is dropped. The reader-side result is unverified: a
page-checked audit, where a person reads the printed cell against the stored row, is needed before any
claim about how many real effects the flag would drop. The next step is to re-extract the documents that
no sample has used and draw a fresh sample from those alone.

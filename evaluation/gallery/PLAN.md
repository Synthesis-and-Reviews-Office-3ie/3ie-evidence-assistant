# Gallery and study-card plan (working notes)

Committed so the build does not depend on a single session's memory.

## Handover (21 November 2026)

The gallery moves to a Claude Code session. In this repository: the survey stays, no
`evaluation/gallery/entries/` and no `scripts/render_gallery.py` are created here, and this file is the
record of decisions. The study-card work, the stability fix and the re-measurement stay here.

## Survey result (49 mapped documents, 974 readable tables)

Method: other/unknown 143, RCT (ITT/TOT/ANCOVA) 18, descriptive means with difference column 13,
matching/PSM/IPW 8, cost-effectiveness 5, multiple-testing adjusted 3, DiD 2, bounds 2, quantile 1, IV 1.

Effect format: other/unknown 143, coefficient 17, mean difference 14, standardised effect size 2,
index/z-score 1, marginal effect 1.

Layout: several rounds 29, several arms 28, subgroup columns or rows 27, SE/t/CI 20, split across pages 11,
two or three header rows 10, control-mean and N rows 9, covariate rows 7, Panel A/B 7, stars only 6,
p-values column 5, controls yes/no 5, footnotes on sign 2, transposed 2.

Caveat: 831 of 974 tables carry no method label at all (the model returned empty lists despite the
instruction, often for non-results tables such as questionnaire modules). The counts are indicative, not
exact; rerun with a stricter "always label" prompt or a second pass if the gallery needs a precise survey.

## Exclusion decision and open question

The instruction excludes any document used in an audit sample, the fresh ten, or the never-used set. Read
literally, that removes 47 of the 49 mapped documents and leaves only `a99618599493` and `d6f0a637496f`,
which makes a 25-35 entry gallery impossible from the mapped corpus.

Confirmed by Lucas on 21 November. Exclude the fresh ten, the never-used set, and any document already
audited at document level. A row-level sample drawn from the 49 does not exclude the document it came from,
so the gallery may use the mapped documents except those three groups. Recorded in `index.json` as the
exclusion policy, not as an open question.

## Entry JSON schema (one file per entry, plus index.json)

    {
      "id": "did-followup-vs-did",
      "source": {"doc_key": "...", "page": 12, "table_label": "Table 4",
                 "bbox_points": [x0, y0, x1, y1]},
      "tags": {"method": ["DiD and triple differences"], "format": ["coefficient"],
               "layout": ["several rounds", "SE, t or CI in brackets below or beside"]},
      "snippet": "short text extract",
      "stored_rows": [{"outcome": "...", "arm": "...", "time_point": "...",
                       "subgroup_or_population": "...", "value": -0.014, "se": 0.03,
                       "effect_type": "main | change-in-effect | effect_size | mediation | ..."}],
      "not_stored": [{"cell": "...", "reason": "control or covariate | fixed effect | balance test | pre-programme gap | correlation | cost ratio | sensitivity statistic | other study"}],
      "rule": "one line"
    }

## Entries to build (target 25-35)

From the survey, the common combinations and the audit failures:

1. RCT ITT with SE below (the dominant method).
2. RCT with several arms and several rounds.
3. Descriptive means with a difference column, difference not stored.
4. Matching/PSM/IPW column.
5. Cost-effectiveness ratio, not stored.
6. Multiple-testing adjusted q-values.
7. DiD over plain follow-up, row by row (the Das `(9=7-8)` vs `(11=9-3)` case).
8. Triple difference.
9. IV first stage vs second stage.
10. Bounds (Lee/Manski).
11. Quantile regression.
12. Reversed A-B benefit (Jalal 2009 Table 3.10).
13. Impact as % of nonparticipant mean (Rahman 2023).
14. Odds-ratio column (121340926 type).
15. Standardised effect-size column (sign from mean difference).
16. Age-group rows (Jalal 2013 type), subgroup partners the effect.
17. Two-arm study, arm kept (Rahman 2023 grants-only vs hybrid).
18. After 2 years vs after 4 years, one time point per row (Sulaiman 2015).
19. Spillover population in the title (Bandiera 2011 "other poor women").
20. GATES / ML heterogeneity output.
21. Covariate rows, not stored.
22. Control-mean and N rows, not stored.
23. Panel A/B stacks.
24. Transposed table (outcomes in columns).
25. Change in effect between rounds, kept as a change.
26. Mediation/pathway, kept labelled.

Picture-matters entries (at least 5): mangled minus in the text layer; subgroups by indentation; a rotated
table; SE on the row below; merged headers.

## Resolved decisions (Lucas, 21 November 2026)

- ITT and TOT/LATE: store both, with the estimand labelled; ITT is used first in synthesis.
- IV first stage: store it, labelled as first stage; the effect flag hides it from the effect view.
- Lee/Manski bounds: not CIs, do not replace them; store `bound_lower`, `bound_upper`, `bound_type` on the
  main effect row, not as separate effects. Migration proposed, not applied until Lucas has seen it.
- Adjusted vs unadjusted and quantile effects: store all, labelled with specification or quantile; mark
  `preferred = true` where the paper states a preferred specification.
- Scope: exclude the fresh ten and the never-used set and any document audited at document level; a
  row-level sample from the 49 does not exclude that document. The three-arm test on the 16 never-used
  documents is a fair comparison of arms but not a fresh test.

## Render and review

`scripts/render_gallery.py` crops each entry's bbox at 200 dpi from the local PDF into
`evaluation/gallery/images/` (git-ignored) and writes `evaluation/gallery/review.html` (git-ignored) with
the crop on the left and the stored rows, non-stored cells, tags and rule on the right.

## Study cards (per document)

One OpenRouter call per document reading abstract, methods/data and results. JSON: methods; arms as
printed; rounds with dates; comparison group; sign conventions and units; spillover and subgroup
populations; table list (label, page, role: main effect, heterogeneity, robustness, balance, first stage,
descriptive, cost); and a page and quote for every field. Never copy findings the paper reports from other
studies. Store with the document (Supabase or beside the extraction output). Write 16 cards, one per
never-used document, as a readable file.

## Reader changes to make (uncommitted until Lucas audits)

Measured: label turnover is 28 to 66 percent between two readings, address turnover 0 to 26 percent.
Reasoning off is cheaper but less stable. The fix is the card, not the reasoning setting.

1. Outcome label from the row header, by code. In `to_estimate` (`src/extraction/table_estimates.py`), when
   the outcome is in the rows (`outcome_in_columns` false), take the outcome from `grid.body[row_number-1][0]`,
   the table's own row-header text, normalised only for whitespace and broken words (collapse runs of
   whitespace, join a word split by a hyphen at a line break). Do not use the model's outcome text for this
   case. When the outcome is in the columns, the column header is already the outcome; take it the same way.
2. Arm, time point, population and subgroup from the card. Pass the document's card into `extract_document`.
   The model may pick each of these only from the card's lists (`card_lists`: arms, time_points, populations)
   or return "not on card". Anything else is dropped to "not on card" and flagged, not stored as free text.
3. The card decides which tables hold results. `role_of_table(card, page, label)`; a table whose role is
   balance, descriptive, first stage (as a table) or cost is not read for main effects. The table reader does
   not run its own results-table decision when the card has an entry for the table.
4. Page-image rows carry a cell address. Extend the vision prompt (`page_vision.VISION_PROMPT`) to return
   `row_index` and `column_index` (1-based within the table) per estimate, and write them to `cell_row` and
   `cell_column` in `_row`, so page-read rows can be compared and audited like text rows.
5. Keep the number fixes: mangled minus, leading decimals, page-image routing. Remove a keyword rule only
   where a gallery entry or a card rule covers the same case, and list every rule removed.

Tests to add: the outcome is taken from the row header (Sulaiman after-2-years row keeps its own header), an
arm not on the card becomes "not on card", a balance table from the card is not read, and a vision row
carries a cell index.

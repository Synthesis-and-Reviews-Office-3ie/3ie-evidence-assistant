"""Re-export of the reader's duplicate rules for the evaluation scripts and backfills."""

from src.extraction.dedupe import combined_labels, keeper_rows, should_combine

keeper = keeper_rows

__all__ = ["combined_labels", "keeper", "keeper_rows", "should_combine"]

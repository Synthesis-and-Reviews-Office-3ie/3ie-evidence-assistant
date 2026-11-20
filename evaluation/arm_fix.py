"""The arm fix now lives in the reader; this re-exports it for the held-out backfills."""

import re

from src.extraction.table_structure import fixed_arm, is_role

PANEL = re.compile(r"panel\s+([a-z0-9]+)", re.I)

__all__ = ["PANEL", "fixed_arm", "is_role"]

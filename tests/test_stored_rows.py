"""Reading stored rows without truncation, and comparing them at printed precision.

Both rules live in `evaluation/stored_rows.py`; the cell reader is in
`evaluation/table_coverage.py`.
"""



from evaluation.stored_rows import classify_miss, decimals, fetch_all, matches
from evaluation.table_coverage import estimate_cells, uncovered


class FakeQuery:
    """A query builder that returns fixed pages, so paging can be tested without a database."""

    def __init__(self, rows, page):
        self.rows = rows
        self.page = page
        self.calls = []

    def range(self, start, end):
        self.calls.append((start, end))
        self._window = self.rows[start:end + 1]
        return self

    def execute(self):
        return type("Result", (), {"data": self._window})()


def test_a_document_larger_than_one_page_is_read_whole():
    rows = [{"i": i} for i in range(2500)]
    query = FakeQuery(rows, 1000)
    got = fetch_all(query)
    assert len(got) == 2500
    assert query.calls == [(0, 999), (1000, 1999), (2000, 2999)]


def test_an_exact_page_of_rows_still_stops():
    query = FakeQuery([{"i": i} for i in range(1000)], 1000)
    assert len(fetch_all(query)) == 1000
    assert query.calls == [(0, 999), (1000, 1999)]


def test_a_printed_value_matches_its_hand_typed_precision():
    assert decimals(2.4) == 1 and decimals(691.149) == 3 and decimals(12000.0) == 0
    assert matches(2.404, [2.4])
    assert matches(6143.406, [6143.0])
    assert matches(691.179, [691.149]) is False
    assert classify_miss(2.404, [2.4]) == "rounded"
    assert classify_miss(2.404, [2.471]) == "absent"
    assert classify_miss(2.404, [2.404]) == "exact"


def test_only_estimate_shaped_cells_are_read_from_a_table():
    text = ("Table 1: Effects\n| Outcome | Cost | Sec |\n| --- | --- | --- |\n"
            "| Income | 107 (148) | 276** |\n| Obs | 2,861 | 2,941 |")
    cells = estimate_cells(text)
    assert 107.0 in cells and 276.0 in cells
    assert 2861.0 not in cells and 2941.0 not in cells


def test_a_cell_without_a_stored_row_is_reported_and_one_with_a_row_is_not():
    stored = [107.0, 148.0]
    assert uncovered([107.0, 1664.0], stored) == [1664.0]
    assert uncovered([107.0], [107.0]) == []

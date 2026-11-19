"""Classification of stored rows by the reader that wrote them."""

from evaluation.accuracy import ROW_FIELDS, classify


def test_the_row_fetch_reads_the_field_that_names_the_writer():
    # text_position is the only field that distinguishes a vision read from a table row. Without it the
    # ten-paper check counted 288 vision rows as table rows with no address.
    assert "text_position" in ROW_FIELDS


def test_rows_are_classified_by_the_reader_that_wrote_them():
    assert classify({"text_position": "page 4, vision read"}) == "vision"
    assert classify({"table_number": "prose", "text_position": "prose read"}) == "prose"
    assert classify({"text_position": "prose read"}) == "prose"
    assert classify({"text_position": "Table 3, row 'Income', column '(1)'"}) == "table"


def test_a_row_without_a_writer_marker_is_a_table_row():
    assert classify({"unit_index": 4}) == "table"
    assert classify({}) == "table"

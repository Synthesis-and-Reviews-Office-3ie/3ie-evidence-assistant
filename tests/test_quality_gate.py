"""The stored-baseline comparison the weekly gate uses for address accuracy."""

from evaluation.accuracy import baseline_entry, below_baseline, rates


def test_rates_divide_by_their_own_base():
    result = {"addressed": 200, "value_ok": 199, "param_printed": 150, "param_ok": 148,
              "table_rows": 250}
    assert rates(result) == {"value": 199 / 200, "parameter": 148 / 150, "addressed": 200 / 250}


def test_rates_are_zero_when_there_is_nothing_to_divide():
    assert rates({"addressed": 0, "value_ok": 0, "param_printed": 0, "param_ok": 0,
                  "table_rows": 0}) == {"value": 0.0, "parameter": 0.0, "addressed": 0.0}


def test_the_baseline_records_the_sample_it_was_measured_on():
    result = {"addressed": 10, "value_ok": 10, "param_printed": 8, "param_ok": 8,
              "table_rows": 12, "documents_with_table_rows": 3, "sample": ["a", "b", "c"]}
    entry = baseline_entry(result)
    assert entry["value"] == 1.0 and entry["parameter"] == 1.0
    assert entry["documents"] == 3 and entry["rows"] == 12
    assert entry["sample"] == ["a", "b", "c"]


def test_a_fall_below_the_baseline_is_a_failure():
    baseline = {"value": 0.999, "parameter": 0.987}
    reasons = below_baseline(baseline, {"value": 0.997, "parameter": 0.990})
    assert reasons == ["value accuracy fell from 99.9% to 99.7%"]


def test_equal_or_improved_rates_are_not_failures():
    baseline = {"value": 0.997, "parameter": 0.987}
    assert below_baseline(baseline, {"value": 0.997, "parameter": 0.987}) == []
    assert below_baseline(baseline, {"value": 1.0, "parameter": 0.99}) == []


def test_a_missing_baseline_or_measurement_is_not_a_failure():
    assert below_baseline(None, {"value": 0.1}) == []
    assert below_baseline({"value": 0.9}, None) == []


def test_a_field_absent_from_the_baseline_or_the_measurement_is_skipped():
    assert below_baseline({"value": 0.999}, {"value": 0.5}) == [
        "value accuracy fell from 99.9% to 50.0%"]
    assert below_baseline({"value": 0.999}, {"parameter": 0.5}) == []

import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validation import ValidationError, clean_input, parse_csv  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "sample_test_input.csv")


def frame(rows):
    return pd.DataFrame(rows, columns=["timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"])


def hourly(n=5, **over):
    rows = [[f"2015-06-16 {10 + i:02d}:00:00", 30.0, 50.0, 100.0] for i in range(n)]
    return frame(rows)


def test_happy_path_sample_first_24():
    df, warnings = clean_input(pd.read_csv(SAMPLE))
    assert len(df) == 24
    assert df["timestamp"].iloc[0] == "2015-06-16 15:00:00"
    assert not df.isna().any().any()
    assert any("forecasting the first 24" in w for w in warnings)


def test_all_rows_and_window():
    raw = pd.read_csv(SAMPLE)
    assert len(clean_input(raw, all_rows=True)[0]) == len(raw)
    assert len(clean_input(raw, window=6)[0]) == 6


def test_missing_columns_is_clear_error():
    with pytest.raises(ValidationError) as e:
        clean_input(pd.DataFrame({"timestamp": ["2015-06-16 10:00:00"], "ambient_temp_c": [30]}))
    assert "missing column: humidity_pct" in e.value.details


def test_column_names_tolerant_of_case_and_space():
    df = hourly(2)
    df.columns = [" Timestamp", "AMBIENT_TEMP_C ", "Humidity_Pct", "solar_irradiance_wm2"]
    out, _ = clean_input(df)
    assert list(out.columns) == ["timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"]


def test_bad_timestamps_dropped_and_all_bad_rejected():
    df = hourly(3)
    df.loc[1, "timestamp"] = "not a date"
    out, w = clean_input(df)
    assert len(out) == 2 and any("unreadable timestamp" in x for x in w)
    with pytest.raises(ValidationError):
        clean_input(frame([["x", 1, 1, 1], ["y", 1, 1, 1]]))


def test_duplicates_dropped_and_sorted():
    df = hourly(3)
    df = pd.concat([df.iloc[[2]], df, df.iloc[[0]]], ignore_index=True)
    out, w = clean_input(df)
    assert out["timestamp"].is_monotonic_increasing and len(out) == 3
    assert any("duplicate" in x for x in w) and any("sorted" in x for x in w)


def test_gap_warning():
    df = hourly(4).drop(index=2).reset_index(drop=True)
    _, w = clean_input(df)
    assert any("gap in hourly sequence" in x for x in w)


def test_nan_interpolated_with_warning():
    df = hourly(3)
    df.loc[1, "humidity_pct"] = None
    df.loc[0, "humidity_pct"] = 40.0
    df.loc[2, "humidity_pct"] = 60.0
    out, w = clean_input(df)
    assert out["humidity_pct"].iloc[1] == pytest.approx(50.0)
    assert any("row 2: humidity_pct missing, interpolated" in x for x in w)


def test_all_missing_column_uses_median():
    df = hourly(3)
    df["humidity_pct"] = None
    out, w = clean_input(df)
    assert (out["humidity_pct"] == 70.7).all()
    assert any("training median" in x for x in w)


def test_out_of_range_values():
    df = hourly(3)
    df.loc[0, "humidity_pct"] = 130
    df.loc[1, "solar_irradiance_wm2"] = -5
    df.loc[2, "ambient_temp_c"] = 99
    out, w = clean_input(df)
    assert out["humidity_pct"].iloc[0] == 100
    assert out["solar_irradiance_wm2"].iloc[1] == 0
    assert out["ambient_temp_c"].iloc[2] == 30.0  # treated as missing, filled from neighbours
    assert len(w) >= 3


def test_non_numeric_treated_as_missing():
    df = hourly(3)
    df["ambient_temp_c"] = df["ambient_temp_c"].astype(object)
    df.loc[1, "ambient_temp_c"] = "hot"
    out, w = clean_input(df)
    assert out["ambient_temp_c"].iloc[1] == 30.0
    assert any("not a number" in x for x in w)


def test_empty_inputs_rejected():
    with pytest.raises(ValidationError):
        clean_input(pd.DataFrame())
    with pytest.raises(ValidationError):
        parse_csv(b"")
    with pytest.raises(ValidationError):
        parse_csv(b"   \n")

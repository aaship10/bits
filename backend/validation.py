"""Input cleaning for /api/forecast. clean_input() returns (clean_df, warnings)."""
import io
import re

import pandas as pd

REQUIRED = ["timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"]
NUMERIC = REQUIRED[1:]
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
TEMP_RANGE = (-30.0, 55.0)
# training medians, used only when a column has no valid value at all
MEDIANS = {"ambient_temp_c": 18.5, "humidity_pct": 70.7}
DAYTIME_IRRADIANCE_FALLBACK = 300.0


class ValidationError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


def _norm(name):
    return re.sub(r"[\s\-]+", "_", str(name).strip().lower())


def parse_csv(raw: bytes) -> pd.DataFrame:
    if not raw or not raw.strip():
        raise ValidationError("The uploaded file is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        return pd.read_csv(io.StringIO(text))
    except Exception as e:
        raise ValidationError("Could not read the file as CSV.", [str(e)])


def clean_input(df: pd.DataFrame, window=24, all_rows=False):
    """Validate and repair raw rows. Raises ValidationError if nothing usable remains."""
    warnings = []
    if df is None or len(df) == 0:
        raise ValidationError("No rows were provided.")

    df = df.copy()
    df.columns = [_norm(c) for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValidationError(
            "Missing required column(s).",
            [f"missing column: {c}" for c in missing] + [f"expected columns: {', '.join(REQUIRED)}"],
        )
    df = df[REQUIRED].copy()
    df["_row"] = range(1, len(df) + 1)

    # timestamps
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    bad = df.loc[ts.isna(), "_row"].tolist()
    if bad:
        warnings.append(f"{len(bad)} row(s) dropped for an unreadable timestamp (rows {_fmt_rows(bad)})")
    df["timestamp"] = ts
    df = df[ts.notna()]
    if df.empty:
        raise ValidationError("No rows with a valid timestamp.", ["timestamps must look like 2015-06-16 15:00:00"])

    # duplicates and ordering
    dup = df.duplicated(subset="timestamp", keep="first")
    if dup.any():
        warnings.append(f"{int(dup.sum())} duplicate timestamp row(s) dropped (kept the first)")
        df = df[~dup]
    if not df["timestamp"].is_monotonic_increasing:
        warnings.append("rows were not in time order; sorted by timestamp")
        df = df.sort_values("timestamp")
    df = df.reset_index(drop=True)

    # numbers and out-of-range values
    for c in NUMERIC:
        coerced = pd.to_numeric(df[c], errors="coerce")
        was_text = df[c].notna() & coerced.isna()
        for r in df.loc[was_text, "_row"]:
            warnings.append(f"row {r}: {c} is not a number, treated as missing")
        df[c] = coerced
    df["humidity_pct"] = _clip(df, "humidity_pct", 0, 100, warnings)
    neg = df["solar_irradiance_wm2"] < 0
    for r in df.loc[neg, "_row"]:
        warnings.append(f"row {r}: solar_irradiance_wm2 below 0, set to 0")
    df.loc[neg, "solar_irradiance_wm2"] = 0.0
    lo, hi = TEMP_RANGE
    out = (df["ambient_temp_c"] < lo) | (df["ambient_temp_c"] > hi)
    for r in df.loc[out, "_row"]:
        warnings.append(f"row {r}: ambient_temp_c outside {lo:g}..{hi:g} C, treated as missing")
    df.loc[out, "ambient_temp_c"] = float("nan")

    # gaps in the hourly sequence
    gaps = df["timestamp"].diff().dropna()
    for i in gaps[gaps != pd.Timedelta(hours=1)].index:
        prev = df.loc[i - 1, "timestamp"]
        warnings.append(f"gap in hourly sequence between {prev:{TS_FORMAT}} and {df.loc[i, 'timestamp']:{TS_FORMAT}}")

    _fill_missing(df, warnings)

    if not all_rows:
        n = max(1, int(window))
        if len(df) > n:
            warnings.append(f"input has {len(df)} rows; forecasting the first {n}")
        df = df.head(n)

    df["timestamp"] = df["timestamp"].dt.strftime(TS_FORMAT)
    return df.drop(columns="_row").reset_index(drop=True), warnings


def _clip(df, col, lo, hi, warnings):
    s = df[col]
    out = (s < lo) | (s > hi)
    for r in df.loc[out, "_row"]:
        warnings.append(f"row {r}: {col} outside {lo}..{hi}, clipped")
    return s.clip(lo, hi)


def _fill_missing(df, warnings):
    idx = df.set_index("timestamp")
    for c in NUMERIC:
        na = df[c].isna()
        if not na.any():
            continue
        filled = idx[c].interpolate(method="time", limit_direction="both")
        method = {r: "interpolated" for r in df.loc[na, "_row"]}
        still = filled.isna()
        if still.any():  # column had no valid value at all
            hours = idx.index.hour
            if c == "solar_irradiance_wm2":
                filled = filled.where(~still, pd.Series([0.0 if (h < 6 or h > 19) else DAYTIME_IRRADIANCE_FALLBACK for h in hours], index=idx.index))
            else:
                filled = filled.fillna(MEDIANS[c])
            for r in df.loc[na & still.values, "_row"]:
                method[r] = "filled with training median"
        df[c] = filled.values
        for r in df.loc[na, "_row"]:
            warnings.append(f"row {r}: {c} missing, {method[r]}")


def _fmt_rows(rows, limit=8):
    s = ", ".join(str(r) for r in rows[:limit])
    return s + (", ..." if len(rows) > limit else "")

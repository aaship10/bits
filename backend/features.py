"""Single source of truth for model features.

Uses ONLY timestamp + ambient_temp_c, humidity_pct, solar_irradiance_wm2 (no demand lags:
the hidden test set has no demand column). Output keeps the original row order and never
contains NaN. predict.py carries its own inline copy of this logic.
"""
import numpy as np
import pandas as pd

RAW_COLUMNS = ["timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"]

COOL_BASE_C = 22.0

# Fixed output order. Chosen by train_local.py's time-based ablation: day_of_week, is_weekend,
# month, day_of_year, heating_deg and temp lags did not lower validation RMSE (demand has no
# weekday effect; month/day_of_year only add extrapolation risk for the hotter test period).
# hour_0..hour_23 one-hots let linear models learn the daily profile and extrapolate in heat.
HOUR_DUMMIES = [f"hour_{h}" for h in range(24)]
FEATURE_COLUMNS = [
    "hour", "hour_sin", "hour_cos", *HOUR_DUMMIES, "is_evening",
    "cooling_deg", "temp_x_humidity", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2",
    "cooling_x_evening", "cooling_x_humidity", "temp_roll3", "temp_roll24", "solar_roll3",
]


def build_features(df: pd.DataFrame, columns=None) -> pd.DataFrame:
    """Return the feature frame for `df`, same row order, no NaN.

    `columns` optionally selects a subset of FEATURE_COLUMNS (kept in contract order).
    """
    ts = pd.to_datetime(df["timestamp"])
    t = pd.to_numeric(df["ambient_temp_c"], errors="coerce").astype(float)
    h = pd.to_numeric(df["humidity_pct"], errors="coerce").astype(float)
    s = pd.to_numeric(df["solar_irradiance_wm2"], errors="coerce").astype(float)

    out = pd.DataFrame(index=df.index)
    hour = ts.dt.hour
    out["hour"] = hour
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    for h_ in range(24):
        out[f"hour_{h_}"] = (hour == h_).astype(int)
    out["is_evening"] = hour.between(18, 22).astype(int)
    out["cooling_deg"] = np.maximum(0.0, t - COOL_BASE_C)
    out["temp_x_humidity"] = t * h
    out["ambient_temp_c"] = t
    out["humidity_pct"] = h
    out["solar_irradiance_wm2"] = s
    out["cooling_x_evening"] = out["cooling_deg"] * out["is_evening"]
    out["cooling_x_humidity"] = out["cooling_deg"] * h

    # Rolling weather means (min_periods=1, so the first rows use what exists): computed in time order, then restored to input order.
    order = np.argsort(ts.values, kind="stable")
    tt, ss = t.iloc[order].reset_index(drop=True), s.iloc[order].reset_index(drop=True)
    lag = pd.DataFrame({
        "temp_roll3": tt.rolling(3, min_periods=1).mean(),
        "temp_roll24": tt.rolling(24, min_periods=1).mean(),
        "solar_roll3": ss.rolling(3, min_periods=1).mean(),
    })
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))
    for c in lag.columns:
        out[c] = lag[c].to_numpy()[inverse]

    out = out[FEATURE_COLUMNS]
    out = out.fillna(0.0)  # safety net: NaN-free contract even for bad input
    if columns is not None:
        out = out[[c for c in FEATURE_COLUMNS if c in set(columns)]]
    return out.astype(float)

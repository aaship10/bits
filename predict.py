"""HackSphere 3.0 demand forecaster: predict(input_df) -> numpy array of kW, one per row.

Calls the published Zoho Catalyst QuickML endpoint. If that fails for ANY reason it falls back
to a ridge model whose coefficients are pasted below, and prints a loud WARNING to stderr.

Configuration (environment variables; never commit values):
  QUICKML_ENDPOINT_URL   deployment URL of the published endpoint (overrides the constant below)
  QUICKML_ENDPOINT_KEY   value for the X-QUICKML-ENDPOINT-KEY header
  QUICKML_CATALYST_ORG   value for the CATALYST-ORG header
  QUICKML_ENVIRONMENT    "Development" or "Production" (default Production)
  QUICKML_ACCESS_TOKEN   a ready OAuth access token, OR the refresh-flow trio:
  QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET / QUICKML_REFRESH_TOKEN
  QUICKML_ACCOUNTS_URL   token host (default https://accounts.zoho.com; use .in/.eu/... per data centre)
  QUICKML_BATCH_SIZE     rows per request (default 50)
Usage: python predict.py --input sample_test_input.csv --output predictions.csv
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

QUICKML_ENDPOINT_URL = "YOUR_PUBLISHED_QUICKML_ENDPOINT_URL_HERE"
TIMEOUT_S = 30
CLIP_KW = (0.0, 500.0)

# ----------------------------------------------------------------------------------------
# Features: inline copy of ml/features.py (graders may run this file alone). Keep in sync.
# ----------------------------------------------------------------------------------------
COOL_BASE_C = 22.0
HOUR_DUMMIES = [f"hour_{h}" for h in range(24)]
FEATURE_COLUMNS = [
    "hour", "hour_sin", "hour_cos", *HOUR_DUMMIES, "is_evening",
    "cooling_deg", "temp_x_humidity", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2",
    "cooling_x_evening", "cooling_x_humidity", "temp_roll3", "temp_roll24", "solar_roll3",
]


def build_features(df):
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
    return out[FEATURE_COLUMNS].fillna(0.0).astype(float)


# ----------------------------------------------------------------------------------------
# Fallback: ridge fitted by ml/train_local.py on all of train_telemetry.csv (raw-feature units)
# ----------------------------------------------------------------------------------------
RIDGE_INTERCEPT = 160.18371
RIDGE_COEFS = {
    "hour_0": -46.777106,
    "hour_1": -45.243388,
    "hour_2": -44.18291,
    "hour_3": -44.835844,
    "hour_4": -45.41369,
    "hour_5": -45.677244,
    "hour_6": -3.3389854,
    "hour_7": 36.167301,
    "hour_8": 36.701415,
    "hour_9": 37.320973,
    "hour_10": 7.0194601,
    "hour_11": 6.2058305,
    "hour_12": 5.3835603,
    "hour_13": 6.7146491,
    "hour_14": 6.7334625,
    "hour_15": 6.5723386,
    "hour_16": 7.6656168,
    "hour_17": 6.8402642,
    "hour_18": 27.102203,
    "hour_19": 28.251806,
    "hour_20": 28.692995,
    "hour_21": 27.902016,
    "hour_22": 27.217423,
    "hour_23": -26.104152,
    "is_evening": 33.663353,
    "cooling_deg": 15.551267,
    "temp_x_humidity": 0.028840355,
    "ambient_temp_c": -2.2780669,
    "humidity_pct": -0.27209847,
    "solar_irradiance_wm2": 0.012706795,
    "cooling_x_evening": -0.078812325,
    "cooling_x_humidity": -0.13039219,
    "temp_roll3": 0.19234891,
    "temp_roll24": -0.3395806,
    "solar_roll3": -0.0097131861,
}


def _fallback_predict(input_df):
    X = build_features(input_df)
    y = np.full(len(X), RIDGE_INTERCEPT, dtype=float)
    for name, w in RIDGE_COEFS.items():
        y += w * X[name].to_numpy()
    return y


def _warn(msg):
    print(f"\n{'!' * 78}\nWARNING: {msg}\n{'!' * 78}\n", file=sys.stderr)


# ----------------------------------------------------------------------------------------
# QuickML call. Request/response shapes: see ml/QUICKML_NOTES.md; only _build_payload and
# _parse_response should need changing once the real endpoint's sample call is known.
# ----------------------------------------------------------------------------------------
_token_cache = {"value": None, "expires": 0.0}


def _access_token():
    static = os.environ.get("QUICKML_ACCESS_TOKEN")
    cid, secret, refresh = (os.environ.get(k) for k in
                            ("QUICKML_CLIENT_ID", "QUICKML_CLIENT_SECRET", "QUICKML_REFRESH_TOKEN"))
    if cid and secret and refresh:
        if _token_cache["value"] and time.time() < _token_cache["expires"] - 60:
            return _token_cache["value"]
        host = os.environ.get("QUICKML_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/")
        r = requests.post(f"{host}/oauth/v2/token", timeout=TIMEOUT_S, data={
            "grant_type": "refresh_token", "client_id": cid, "client_secret": secret,
            "refresh_token": refresh})
        r.raise_for_status()
        body = r.json()
        if "access_token" not in body:
            raise RuntimeError(f"token refresh failed: {body}")
        _token_cache.update(value=body["access_token"],
                            expires=time.time() + float(body.get("expires_in", 3600)))
        return _token_cache["value"]
    if static:
        return static
    raise RuntimeError("no QuickML credentials in environment")


def _headers():
    h = {"Content-Type": "application/json",
         "Authorization": f"Zoho-oauthtoken {_access_token()}",
         "Environment": os.environ.get("QUICKML_ENVIRONMENT", "Production")}
    if os.environ.get("QUICKML_ENDPOINT_KEY"):
        h["X-QUICKML-ENDPOINT-KEY"] = os.environ["QUICKML_ENDPOINT_KEY"]
    if os.environ.get("QUICKML_CATALYST_ORG"):
        h["CATALYST-ORG"] = os.environ["QUICKML_CATALYST_ORG"]
    return h


def _build_payload(feature_rows):
    return {"data": feature_rows}  # TODO confirm against the endpoint's sample request


def _parse_response(body, n):
    """Accept {'predictions': [...]}, {'result': [...]}, or a bare list of numbers/dicts."""
    items = body
    if isinstance(body, dict):
        for key in ("predictions", "result", "results", "prediction", "data"):
            if key in body:
                items = body[key]
                break
    if not isinstance(items, list):
        items = [items]
    vals = []
    for it in items:
        if isinstance(it, dict):
            it = next((it[k] for k in ("prediction", "target_demand_kw", "output", "value")
                       if k in it), next(iter(it.values())))
        vals.append(float(it))
    if len(vals) != n:
        raise ValueError(f"expected {n} predictions, got {len(vals)}")
    return np.array(vals, dtype=float)


def _quickml_predict(input_df):
    url = os.environ.get("QUICKML_ENDPOINT_URL", QUICKML_ENDPOINT_URL)
    if not url or url.startswith("YOUR_"):
        raise RuntimeError("QUICKML_ENDPOINT_URL is not configured")
    feats = build_features(input_df)
    batch = int(os.environ.get("QUICKML_BATCH_SIZE", 50))
    parts = []
    for i in range(0, len(feats), batch):
        rows = feats.iloc[i:i + batch].to_dict(orient="records")
        for attempt in (1, 2):  # one retry
            try:
                r = requests.post(url, json=_build_payload(rows), headers=_headers(),
                                  timeout=TIMEOUT_S)
                r.raise_for_status()
                parts.append(_parse_response(r.json(), len(rows)))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise RuntimeError(f"batch starting at row {i}: {e}") from e
                time.sleep(1.5)
    return np.concatenate(parts)


def predict(input_df: pd.DataFrame):
    """input_df columns: timestamp, ambient_temp_c, humidity_pct, solar_irradiance_wm2.
    Returns numpy array of predicted demand (kW), one finite value per row, input order."""
    input_df = input_df.reset_index(drop=True)
    try:
        preds = _quickml_predict(input_df)
        if not np.isfinite(preds).all():
            raise ValueError("QuickML returned NaN/inf")
    except Exception as e:  # noqa: BLE001
        _warn(f"QuickML endpoint call failed ({e}). "
              "USING LOCAL RIDGE FALLBACK - not the QuickML model.")
        preds = _fallback_predict(input_df)
    return np.clip(np.nan_to_num(preds, nan=157.0, posinf=CLIP_KW[1], neginf=CLIP_KW[0]), *CLIP_KW)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="HackSphere demand predictor")
    ap.add_argument("--input", help="CSV with timestamp + 3 weather columns")
    ap.add_argument("--output", help="where to write timestamp,target_demand_kw")
    args = ap.parse_args()
    if args.input:
        df = pd.read_csv(args.input)
        preds = predict(df)
        out = pd.DataFrame({"timestamp": df["timestamp"], "target_demand_kw": np.round(preds, 2)})
        out.to_csv(args.output or "predictions.csv", index=False)
        print(f"Wrote {len(out)} predictions to {args.output or 'predictions.csv'}")
    else:
        print("Testing predict.py on sample_test_input.csv...")
        sample_df = pd.read_csv("sample_test_input.csv")
        preds = predict(sample_df)
        print(f"Generated {len(preds)} predictions. First 5 samples:\n{preds[:5]}")

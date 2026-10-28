"""Calls the published QuickML endpoint; falls back to a local model if it fails.

Per the Catalyst QuickML docs a published endpoint is a POST to the deployment URL with
headers X-QUICKML-ENDPOINT-KEY, Authorization: Zoho-oauthtoken <token>, CATALYST-ORG and
Environment. Confirmed shape (ml/QUICKML_NOTES.md): ONE row per call,
  request  {"data": {<38 feature columns from features.build_features>}}
  response {"result": [<kW>]}
So a forecast of N rows costs N endpoint calls (the free tier allows only ~500 in total).
On HTTP 401/402/403/429 (auth or quota) the remaining calls are cancelled and the ridge
fallback is used for the whole request.

Environment variables (names only):
  QUICKML_ENDPOINT_URL        deployment URL (unset -> fallback model)
  QUICKML_ENDPOINT_KEY        value for X-QUICKML-ENDPOINT-KEY
  CATALYST_ORG_ID             value for CATALYST-ORG
  QUICKML_ENVIRONMENT         Development | Production (default Production)
  QUICKML_ACCESS_TOKEN        static token (expires about hourly), or instead:
  QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET / QUICKML_REFRESH_TOKEN  to auto-refresh
  ZOHO_ACCOUNTS_URL           default https://accounts.zoho.com (change per data centre)
  QUICKML_WORKERS             parallel calls (default 8)
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from features import build_features

TIMEOUT_S = 30
WORKERS = int(os.environ.get("QUICKML_WORKERS", "8"))
FATAL_STATUS = (401, 402, 403, 429)  # auth / quota: retrying cannot help, stop calling

_token = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()


def endpoint_url():
    return os.environ.get("QUICKML_ENDPOINT_URL", "").strip()


def _access_token():
    static = os.environ.get("QUICKML_ACCESS_TOKEN", "").strip()
    refresh = os.environ.get("QUICKML_REFRESH_TOKEN", "").strip()
    if not refresh:
        return static
    with _token_lock:
        if _token["value"] and time.time() < _token["expires"] - 60:
            return _token["value"]
        r = requests.post(
            os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/") + "/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": os.environ.get("QUICKML_CLIENT_ID", ""),
                "client_secret": os.environ.get("QUICKML_CLIENT_SECRET", ""),
            },
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        if "access_token" not in j:
            raise RuntimeError(f"token refresh failed: {j.get('error', j)}")
        _token["value"] = j["access_token"]
        _token["expires"] = time.time() + float(j.get("expires_in", 3600))
        return _token["value"]


def _headers():
    h = {"Content-Type": "application/json", "Environment": os.environ.get("QUICKML_ENVIRONMENT", "Production")}
    if os.environ.get("QUICKML_ENDPOINT_KEY"):
        h["X-QUICKML-ENDPOINT-KEY"] = os.environ["QUICKML_ENDPOINT_KEY"]
    if os.environ.get("CATALYST_ORG_ID"):
        h["CATALYST-ORG"] = os.environ["CATALYST_ORG_ID"]
    token = _access_token()
    if token:
        h["Authorization"] = f"Zoho-oauthtoken {token}"
    return h


# Ridge fallback fitted by ml/train_local.py on all of train_telemetry.csv (same values as the
# root predict.py). Validation RMSE about 9 kW.
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


def fallback_predict(df: pd.DataFrame) -> np.ndarray:
    X = build_features(df)
    y = np.full(len(X), RIDGE_INTERCEPT, dtype=float)
    for name, w in RIDGE_COEFS.items():
        y += w * X[name].to_numpy()
    return np.clip(y, 0, 500)


def _build_body(row: dict) -> dict:
    return {"data": row}


def _parse_response(j, n: int) -> np.ndarray:
    if isinstance(j, dict):
        for k in ("predictions", "prediction", "result", "data", "output"):
            if k in j:
                return _parse_response(j[k], n)
        raise ValueError(f"unrecognised response keys: {list(j)[:5]}")
    if isinstance(j, list):
        vals = []
        for item in j:
            if isinstance(item, dict):  # e.g. [{"target_demand_kw": 150.2}]
                nums = [v for v in item.values() if isinstance(v, (int, float))]
                item = item.get("target_demand_kw", nums[-1] if nums else None)
            vals.append(item)
        return np.array(vals, dtype=float)
    raise ValueError("unrecognised response shape")


def _call_row(row: dict, headers: dict, abort: threading.Event) -> float:
    """One endpoint call for one feature row; one retry on ordinary errors."""
    last = None
    for _ in range(2):
        if abort.is_set():
            raise RuntimeError("cancelled after an earlier failure")
        try:
            r = requests.post(endpoint_url(), json=_build_body(row), headers=headers, timeout=TIMEOUT_S)
            if r.status_code in FATAL_STATUS:
                abort.set()
                raise RuntimeError(f"HTTP {r.status_code} from QuickML: {str(getattr(r, 'text', ''))[:200]}")
            r.raise_for_status()
            preds = _parse_response(r.json(), 1)
            if len(preds) != 1 or not np.isfinite(preds).all():
                raise ValueError("endpoint returned the wrong number of predictions or a non-finite value")
            return float(preds[0])
        except Exception as e:  # noqa: BLE001
            last = e
            if abort.is_set():
                break
    abort.set()  # stop spending calls on the remaining rows
    raise last


def predict(df: pd.DataFrame):
    """Return (predictions, model_source, error). error is None when QuickML answered."""
    if not endpoint_url():
        return fallback_predict(df), "fallback", "QUICKML_ENDPOINT_URL is not set"
    try:
        rows = build_features(df).to_dict(orient="records")
        headers = _headers()  # token refresh happens once, not in every worker thread
        abort = threading.Event()  # per request, so concurrent requests do not cancel each other
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:  # map keeps the row order
            vals = list(pool.map(lambda r: _call_row(r, headers, abort), rows))
        return np.clip(np.array(vals, dtype=float), 0, 500), "quickml", None
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: QuickML call failed, using fallback model: {e}", file=sys.stderr, flush=True)
        return fallback_predict(df), "fallback", str(e)


def is_reachable() -> bool:
    if not endpoint_url():
        return False
    try:
        requests.get(endpoint_url(), timeout=3)
        return True  # any HTTP answer means the host is up; no credentials sent on a probe
    except Exception:  # noqa: BLE001
        return False

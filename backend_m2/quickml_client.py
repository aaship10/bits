"""Calls the published QuickML endpoint; falls back to a local model if it fails.

Per the Catalyst QuickML docs a published endpoint is a POST to the deployment URL with
headers X-QUICKML-ENDPOINT-KEY, Authorization: Zoho-oauthtoken <token>, CATALYST-ORG and
Environment. The docs do not show the body/response shape, so the body defaults to the
predict.py template shape ({"data": [...]}) and the response parser accepts several
common shapes. Adjust _build_body()/_parse_response() to match ml/QUICKML_NOTES.md.

Environment variables (names only):
  QUICKML_ENDPOINT_URL        deployment URL (unset -> fallback model)
  QUICKML_ENDPOINT_KEY        value for X-QUICKML-ENDPOINT-KEY
  CATALYST_ORG_ID             value for CATALYST-ORG
  QUICKML_ENVIRONMENT         Development | Production (default Production)
  QUICKML_ACCESS_TOKEN        static token (expires about hourly), or instead:
  QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET / QUICKML_REFRESH_TOKEN  to auto-refresh
  ZOHO_ACCOUNTS_URL           default https://accounts.zoho.com (change per data centre)
"""
import os
import sys
import threading
import time

import numpy as np
import pandas as pd
import requests

TIMEOUT_S = 30
BATCH_SIZE = int(os.environ.get("QUICKML_BATCH_SIZE", "500"))

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


def fallback_predict(df: pd.DataFrame) -> np.ndarray:
    """Placeholder model (same formula as the predict.py template). Replace with the
    ridge coefficients from Member 1's predict.py once available."""
    hours = pd.to_datetime(df["timestamp"]).dt.hour
    base = 120.0 + 30.0 * np.sin(2 * np.pi * (hours - 6) / 24)
    cooling = np.maximum(0.0, df["ambient_temp_c"] - 24.0) * 8.5
    return np.clip((base + cooling).values.astype(float), 0, 500)


def _build_body(batch: pd.DataFrame) -> dict:
    return {"data": batch.to_dict(orient="records")}


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


def _call_endpoint(batch: pd.DataFrame) -> np.ndarray:
    last = None
    for _ in range(2):  # one retry
        try:
            r = requests.post(endpoint_url(), json=_build_body(batch), headers=_headers(), timeout=TIMEOUT_S)
            r.raise_for_status()
            preds = _parse_response(r.json(), len(batch))
            if len(preds) != len(batch) or not np.isfinite(preds).all():
                raise ValueError("endpoint returned the wrong number of predictions or non-finite values")
            return preds
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def predict(df: pd.DataFrame):
    """Return (predictions, model_source, error). error is None when QuickML answered."""
    if not endpoint_url():
        return fallback_predict(df), "fallback", "QUICKML_ENDPOINT_URL is not set"
    try:
        parts = [_call_endpoint(df.iloc[i:i + BATCH_SIZE]) for i in range(0, len(df), BATCH_SIZE)]
        return np.clip(np.concatenate(parts), 0, 500), "quickml", None
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

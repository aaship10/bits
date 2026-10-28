import os
import sys
import threading

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import quickml_client as q  # noqa: E402
from features import FEATURE_COLUMNS  # noqa: E402

DF = pd.DataFrame({"timestamp": ["2015-06-16 15:00:00", "2015-06-16 16:00:00"],
                   "ambient_temp_c": [35.0, 30.0], "humidity_pct": [50.0, 50.0],
                   "solar_irradiance_wm2": [100.0, 80.0]})
URL = "https://example.test/predict"


class Resp:
    def __init__(self, j, status=200, text=""):
        self.j, self.status_code, self.text = j, status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} error")

    def json(self):
        return self.j


def test_no_endpoint_uses_fallback(monkeypatch):
    monkeypatch.delenv("QUICKML_ENDPOINT_URL", raising=False)
    preds, src, err = q.predict(DF)
    assert src == "fallback" and err and len(preds) == 2 and np.isfinite(preds).all()


def test_fallback_is_ridge_not_placeholder():
    # A hot evening hour must come out well above a cool overnight hour.
    df = pd.DataFrame({"timestamp": ["2015-06-17 03:00:00", "2015-06-17 20:00:00"],
                       "ambient_temp_c": [26.0, 35.0], "humidity_pct": [60.0, 40.0],
                       "solar_irradiance_wm2": [0.0, 0.0]})
    p = q.fallback_predict(df)
    assert p[0] < 130 < 200 < p[1] <= 500


def test_one_row_per_call_with_38_features_in_order(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)
    bodies = []

    def fake_post(url, json=None, **k):
        bodies.append(json)
        return Resp({"result": [100.0 + len(bodies)]})

    monkeypatch.setattr(q.requests, "post", fake_post)
    preds, src, err = q.predict(DF)
    assert src == "quickml" and err is None and len(preds) == 2
    assert len(bodies) == 2
    for b in bodies:
        assert list(b) == ["data"] and isinstance(b["data"], dict)
        assert list(b["data"]) == FEATURE_COLUMNS and len(b["data"]) == 38


def test_order_preserved_across_parallel_calls(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)
    df = pd.DataFrame({"timestamp": pd.date_range("2015-06-16", periods=30, freq="h").strftime("%Y-%m-%d %H:%M:%S"),
                       "ambient_temp_c": np.arange(30, dtype=float), "humidity_pct": 50.0,
                       "solar_irradiance_wm2": 0.0})
    # echo ambient_temp_c back as the prediction so row order is visible
    monkeypatch.setattr(q.requests, "post",
                        lambda url, json=None, **k: Resp({"result": [json["data"]["ambient_temp_c"] * 5]}))
    preds, src, _ = q.predict(df)
    assert src == "quickml" and list(preds) == [float(i * 5) for i in range(30)]


@pytest.mark.parametrize("payload", [{"result": [150.5]}, {"predictions": [150.5]}, [150.5],
                                     {"result": [{"target_demand_kw": 150.5}]}])
def test_endpoint_response_shapes(monkeypatch, payload):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)
    monkeypatch.setattr(q.requests, "post", lambda *a, **k: Resp(payload))
    preds, src, err = q.predict(DF)
    assert src == "quickml" and err is None and list(preds) == [150.5, 150.5]


def test_endpoint_failure_falls_back_after_one_retry(monkeypatch):
    calls = []
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(q.requests, "post", boom)
    preds, src, err = q.predict(DF.head(1))
    assert src == "fallback" and "down" in err and len(calls) == 2 and len(preds) == 1


def test_wrong_length_rejected(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)
    monkeypatch.setattr(q.requests, "post", lambda *a, **k: Resp({"result": [1.0, 2.0]}))
    assert q.predict(DF)[1] == "fallback"


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_auth_or_quota_error_aborts_after_first_workers(monkeypatch, status):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", URL)
    lock, calls = threading.Lock(), []

    def refuse(*a, **k):
        with lock:
            calls.append(1)
        return Resp({}, status=status, text="quota used up")

    monkeypatch.setattr(q.requests, "post", refuse)
    df = pd.DataFrame({"timestamp": pd.date_range("2015-06-16", periods=100, freq="h").strftime("%Y-%m-%d %H:%M:%S"),
                       "ambient_temp_c": 30.0, "humidity_pct": 50.0, "solar_irradiance_wm2": 0.0})
    preds, src, err = q.predict(df)
    assert src == "fallback" and str(status) in err and len(preds) == 100 and np.isfinite(preds).all()
    assert len(calls) <= q.WORKERS  # no retries, nothing queued behind the first batch


def test_headers_follow_catalyst_docs(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_KEY", "k")
    monkeypatch.setenv("CATALYST_ORG_ID", "o")
    monkeypatch.setenv("QUICKML_ACCESS_TOKEN", "t")
    monkeypatch.delenv("QUICKML_REFRESH_TOKEN", raising=False)
    h = q._headers()
    assert h["X-QUICKML-ENDPOINT-KEY"] == "k" and h["CATALYST-ORG"] == "o"
    assert h["Authorization"] == "Zoho-oauthtoken t"

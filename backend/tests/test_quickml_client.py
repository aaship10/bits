import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import quickml_client as q  # noqa: E402

DF = pd.DataFrame({"timestamp": ["2015-06-16 15:00:00", "2015-06-16 16:00:00"],
                   "ambient_temp_c": [35.0, 30.0], "humidity_pct": [50.0, 50.0],
                   "solar_irradiance_wm2": [100.0, 80.0]})


class Resp:
    def __init__(self, j):
        self.j = j

    def raise_for_status(self):
        pass

    def json(self):
        return self.j


def test_no_endpoint_uses_fallback(monkeypatch):
    monkeypatch.delenv("QUICKML_ENDPOINT_URL", raising=False)
    preds, src, err = q.predict(DF)
    assert src == "fallback" and err and len(preds) == 2 and np.isfinite(preds).all()


@pytest.mark.parametrize("payload", [{"predictions": [150.5, 160.25]}, [150.5, 160.25],
                                     {"result": [{"target_demand_kw": 150.5}, {"target_demand_kw": 160.25}]}])
def test_endpoint_response_shapes(monkeypatch, payload):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.test/predict")
    monkeypatch.setattr(q.requests, "post", lambda *a, **k: Resp(payload))
    preds, src, err = q.predict(DF)
    assert src == "quickml" and err is None and list(preds) == [150.5, 160.25]


def test_endpoint_failure_falls_back_after_retry(monkeypatch):
    calls = []
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.test/predict")

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(q.requests, "post", boom)
    preds, src, err = q.predict(DF)
    assert src == "fallback" and "down" in err and len(calls) == 2


def test_wrong_length_rejected(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.test/predict")
    monkeypatch.setattr(q.requests, "post", lambda *a, **k: Resp({"predictions": [1.0]}))
    assert q.predict(DF)[1] == "fallback"


def test_headers_follow_catalyst_docs(monkeypatch):
    monkeypatch.setenv("QUICKML_ENDPOINT_KEY", "k")
    monkeypatch.setenv("CATALYST_ORG_ID", "o")
    monkeypatch.setenv("QUICKML_ACCESS_TOKEN", "t")
    monkeypatch.delenv("QUICKML_REFRESH_TOKEN", raising=False)
    h = q._headers()
    assert h["X-QUICKML-ENDPOINT-KEY"] == "k" and h["CATALYST-ORG"] == "o"
    assert h["Authorization"] == "Zoho-oauthtoken t"

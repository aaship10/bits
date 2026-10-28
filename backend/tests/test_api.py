import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("QUICKML_ENDPOINT_URL", None)
os.environ["STORAGE_BACKEND"] = "memory"
import app as app_module  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "sample_test_input.csv")
HOUR_KEYS = {"timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2", "predicted_kw",
             "grid_mode", "mode_reason", "overload_alert", "battery_soc_pct", "battery_low"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("uploads.LOCAL_DIR", str(tmp_path))
    return app_module.app.test_client()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_forecast_csv_upload_matches_contract(client):
    with open(SAMPLE, "rb") as f:
        r = client.post("/api/forecast", data={"file": (io.BytesIO(f.read()), "sample.csv")},
                        content_type="multipart/form-data")
    assert r.status_code == 200
    j = r.json
    assert j["model_source"] == "fallback" and len(j["hours"]) == 24
    assert set(j["hours"][0]) == HOUR_KEYS
    assert set(j["summary"]) == {"peak_kw", "peak_timestamp", "storage_hours", "main_grid_hours",
                                 "overload_hours", "min_soc_pct"}
    assert j["summary"]["storage_hours"] + j["summary"]["main_grid_hours"] == 24


def test_forecast_json_then_latest_and_logs(client):
    rows = [{"timestamp": f"2015-06-16 {h:02d}:00:00", "ambient_temp_c": 30, "humidity_pct": 50,
             "solar_irradiance_wm2": 100} for h in range(8, 20)]
    r = client.post("/api/forecast?window=12", json={"rows": rows})
    assert r.status_code == 200 and len(r.json["hours"]) == 12
    assert client.get("/api/forecast/latest").json["forecast_id"] == r.json["forecast_id"]
    logs = client.get("/api/logs?limit=5").json["logs"]
    assert logs and set(logs[0]) == {"time", "level", "event", "message", "forecast_id"}


def test_bad_requests_return_400_with_error(client):
    r = client.post("/api/forecast", json={"nope": 1})
    assert r.status_code == 400 and "error" in r.json
    r = client.post("/api/forecast", json={"rows": [{"timestamp": "2015-06-16 10:00:00"}]})
    assert r.status_code == 400 and r.json["details"]
    r = client.post("/api/forecast?window=abc", json={"rows": [{"a": 1}]})
    assert r.status_code == 400


def test_cors_header(client):
    r = client.get("/api/health", headers={"Origin": "https://example.com"})
    assert r.headers.get("Access-Control-Allow-Origin")

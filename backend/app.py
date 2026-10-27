"""HackSphere 3.0 backend (Member 2). Flask app for Catalyst AppSail.

Run locally:  python app.py   (port from X_ZOHO_CATALYST_LISTEN_PORT or PORT, default 5000)
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

import quickml_client
import uploads
from validation import ValidationError, clean_input, parse_csv

# Use Member 3's modules when present, otherwise the built-in stand-ins.
try:
    import controller, battery, storage  # type: ignore
except ImportError:
    import _fallbacks as controller
    battery = storage = controller

app = Flask(__name__)
CORS(app)

MAX_ROWS = 20000


@app.errorhandler(ValidationError)
def _validation_error(e):
    return jsonify({"error": e.message, "details": e.details}), 400


@app.errorhandler(404)
def _not_found(_):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(Exception)
def _unexpected(e):
    app.logger.exception("unhandled error")
    return jsonify({"error": "Internal server error", "details": [str(e)]}), 500


def _read_request():
    """Return (raw_df, raw_csv_bytes_or_None, filename)."""
    if "file" in request.files:
        f = request.files["file"]
        raw = f.read()
        return parse_csv(raw), raw, f.filename or "upload.csv"
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
        raise ValidationError('Send JSON {"rows": [...]} or a multipart CSV in field "file".')
    if not body["rows"]:
        raise ValidationError("No rows were provided.")
    if not all(isinstance(r, dict) for r in body["rows"]):
        raise ValidationError('Each entry in "rows" must be an object.')
    return pd.DataFrame(body["rows"]), None, "rows.json"


def _summary(hours):
    peak = max(hours, key=lambda h: h["predicted_kw"])
    return {
        "peak_kw": peak["predicted_kw"],
        "peak_timestamp": peak["timestamp"],
        "storage_hours": sum(h["grid_mode"] == "RENEWABLE_STORAGE" for h in hours),
        "main_grid_hours": sum(h["grid_mode"] == "MAIN_GRID" for h in hours),
        "overload_hours": sum(bool(h["overload_alert"]) for h in hours),
        "min_soc_pct": min(h["battery_soc_pct"] for h in hours),
    }


def _battery_low_events(hours):
    events, was_low = [], False
    for h in hours:
        if h["battery_low"] and not was_low:
            events.append({"timestamp": h["timestamp"], "type": "BATTERY_LOW", "level": "WARN",
                           "message": f"Battery below 20% ({h['battery_soc_pct']}%) at {h['timestamp']}"})
        was_low = h["battery_low"]
    return events


@app.post("/api/forecast")
def forecast():
    raw_df, raw_bytes, filename = _read_request()
    if len(raw_df) > MAX_ROWS:
        raise ValidationError(f"Too many rows (max {MAX_ROWS}).")

    all_rows = request.args.get("all", "").lower() in ("1", "true", "yes")
    try:
        window = int(request.args.get("window", 24))
    except ValueError:
        raise ValidationError("window must be a whole number.")
    df, warnings = clean_input(raw_df, window=window, all_rows=all_rows)

    now = datetime.now(timezone.utc)
    forecast_id = "f_" + now.strftime("%Y%m%d_%H%M%S")
    storage.log_event("INFO", "UPLOAD", f"Received {len(raw_df)} row(s) from {filename}; forecasting {len(df)}", forecast_id)
    if raw_bytes is not None:
        try:
            uploads.save_raw(raw_bytes, forecast_id, filename, req=request)
        except Exception as e:  # noqa: BLE001  never fail the forecast over archiving
            warnings.append(f"raw upload could not be archived: {e}")

    preds, source, error = quickml_client.predict(df)
    if error:
        storage.log_event("WARN", "QUICKML_ERROR", f"Using fallback model: {error}", forecast_id)

    hours = df.to_dict(orient="records")
    for h, p in zip(hours, preds):
        h["predicted_kw"] = float(p)
    hours = controller.apply_rules(hours)
    hours = battery.simulate(hours)
    events = controller.detect_events(hours) + _battery_low_events(hours)
    events.sort(key=lambda e: e["timestamp"])

    for e in events:
        storage.log_event(e.get("level", "INFO"), e["type"], e["message"], forecast_id)

    result = {
        "forecast_id": forecast_id,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_source": source,
        "hours": hours,
        "events": [{"timestamp": e["timestamp"], "type": e["type"], "message": e["message"]} for e in events],
        "summary": _summary(hours),
        "warnings": warnings,
    }
    storage.save_forecast(json.loads(json.dumps(result)))
    return jsonify(result)


@app.get("/api/forecast/latest")
def latest():
    f = storage.get_latest_forecast()
    if not f:
        return jsonify({"error": "No forecast yet"}), 404
    return jsonify(f)


@app.get("/api/logs")
def logs():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 500)
    except ValueError:
        limit = 50
    return jsonify({"logs": storage.get_logs(limit)})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "quickml": "reachable" if quickml_client.is_reachable() else "unreachable"})


if __name__ == "__main__":
    port = int(os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT") or os.environ.get("PORT") or 5000)
    app.run(host="0.0.0.0", port=port)

"""HackSphere 3.0 backend (Member 2). Flask app for Catalyst AppSail.

Run locally:  python app.py   (port from X_ZOHO_CATALYST_LISTEN_PORT or PORT, default 5000)
"""
import os
from datetime import datetime, timezone

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

import quickml_client
import uploads
from validation import ValidationError, clean_input, parse_csv

import battery
import controller
import storage

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


_last_id = {"base": None, "n": 0}


def _new_forecast_id(now):
    """f_YYYYMMDD_HHMMSS, with a _2, _3... suffix if two forecasts land in the same second."""
    base = "f_" + now.strftime("%Y%m%d_%H%M%S")
    if _last_id["base"] == base:
        _last_id["n"] += 1
        return f"{base}_{_last_id['n']}"
    _last_id.update(base=base, n=1)
    return base


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
    forecast_id = _new_forecast_id(now)
    if raw_bytes is not None:
        try:
            uploads.save_raw(raw_bytes, forecast_id, filename, req=request)
        except Exception as e:  # noqa: BLE001  never fail the forecast over archiving
            warnings.append(f"raw upload could not be archived: {e}")

    preds, source, error = quickml_client.predict(df)

    hours = df.to_dict(orient="records")
    for h, p in zip(hours, preds):
        h["predicted_kw"] = float(p)
    hours = controller.apply_rules(hours)
    hours, battery_events = battery.simulate(hours)
    events = controller.sort_events(controller.detect_events(hours), battery_events)

    result = {
        "forecast_id": forecast_id,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_source": source,
        "hours": hours,
        "events": events,
        "summary": controller.summarize(hours),
        "warnings": warnings,
    }
    storage.save_forecast(result)  # also writes the UPLOAD and per-event log rows
    if error:
        storage.log_event("WARN", "QUICKML_ERROR", f"Using fallback model: {error}", forecast_id)
    result["events"] = [{k: e[k] for k in ("timestamp", "type", "message")} for e in events]
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

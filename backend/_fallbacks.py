"""Minimal stand-ins for Member 3's controller.py, battery.py and storage.py.

app.py imports the real modules when they exist and uses these otherwise, so the API
works end to end before Member 3 delivers. Rules follow the shared contracts.
"""
import threading
from datetime import datetime, timezone

EVENING_HOURS = {18, 19, 20, 21, 22}


# ---- controller ----
def classify_hour(predicted_kw, timestamp):
    kw = round(float(predicted_kw), 2)
    hour = datetime.strptime(str(timestamp)[:19], "%Y-%m-%d %H:%M:%S").hour
    over, evening = kw > 160, hour in EVENING_HOURS
    reason = "both" if over and evening else "demand_over_160" if over else "evening_window" if evening else "normal"
    return {
        "grid_mode": "RENEWABLE_STORAGE" if over or evening else "MAIN_GRID",
        "mode_reason": reason,
        "overload_alert": kw >= 200,
    }


def apply_rules(hours):
    for h in hours:
        h["predicted_kw"] = round(float(h["predicted_kw"]), 2)
        h.update(classify_hour(h["predicted_kw"], h["timestamp"]))
    return hours


def detect_events(hours):
    events, prev = [], None
    for h in hours:
        if prev is not None and h["grid_mode"] != prev["grid_mode"]:
            events.append({"timestamp": h["timestamp"], "type": "MODE_SWITCH", "level": "INFO",
                           "message": f"{prev['grid_mode']} -> {h['grid_mode']} ({h['mode_reason']})"})
        if h["overload_alert"]:
            events.append({"timestamp": h["timestamp"], "type": "OVERLOAD", "level": "CRITICAL",
                           "message": f"Overload: {h['predicted_kw']} kW at {h['timestamp']}"})
        prev = h
    return events


# ---- battery ----
CAPACITY_KWH = 2000.0
START_SOC_PCT = 90.0
LOW_SOC_PCT = 20.0
GRID_CHARGE_KW = 150.0
SOLAR_ARRAY_KW = 200.0


def simulate(hours):
    kwh = CAPACITY_KWH * START_SOC_PCT / 100
    for h in hours:
        if h["grid_mode"] == "RENEWABLE_STORAGE":
            kwh -= h["predicted_kw"]
        else:
            kwh += GRID_CHARGE_KW
        kwh += h["solar_irradiance_wm2"] / 1000 * SOLAR_ARRAY_KW
        kwh = min(max(kwh, 0.0), CAPACITY_KWH)
        soc = kwh / CAPACITY_KWH * 100
        h["battery_soc_pct"] = round(soc, 1)
        h["battery_low"] = soc < LOW_SOC_PCT
    return hours


# ---- storage (in memory) ----
_lock = threading.Lock()
_latest = None
_logs = []


def save_forecast(forecast):
    global _latest
    with _lock:
        _latest = forecast


def get_latest_forecast():
    return _latest


def log_event(level, event, message, forecast_id=None):
    entry = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "level": level,
             "event": event, "message": message, "forecast_id": forecast_id}
    with _lock:
        _logs.append(entry)
    return entry


def get_logs(limit=50):
    with _lock:
        return list(reversed(_logs))[: int(limit)]

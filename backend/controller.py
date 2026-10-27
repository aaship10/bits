"""Transition controller: grid-mode rules, overload alerts and mode-switch events.

Pure functions, no I/O. Rules (HackSphere 3.0 brief, section 6), applied to the
predicted demand rounded to 2 decimals:

    grid_mode = RENEWABLE_STORAGE  if predicted_kw > 160 or hour in 18..22
                MAIN_GRID          otherwise
    overload_alert = predicted_kw >= 200         (independent of grid_mode)

Rounding happens first, with round_kw(), so the number shown on screen and the
badge next to it always agree. Use round_kw() (not the built-in round()) for the
predicted_kw you send to the frontend.
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

# --- Tunable constants -------------------------------------------------------
STORAGE_THRESHOLD_KW = Decimal("160")   # strictly greater than -> storage
OVERLOAD_THRESHOLD_KW = Decimal("200")  # greater than or equal -> critical alert
EVENING_START_HOUR = 18                 # inclusive
EVENING_END_HOUR = 22                   # inclusive (22:00 is inside, 23:00 is not)

MAIN_GRID = "MAIN_GRID"
RENEWABLE_STORAGE = "RENEWABLE_STORAGE"

REASON_DEMAND = "demand_over_160"
REASON_EVENING = "evening_window"
REASON_BOTH = "both"
REASON_NORMAL = "normal"

EVENT_MODE_SWITCH = "MODE_SWITCH"
EVENT_OVERLOAD = "OVERLOAD"
EVENT_BATTERY_LOW = "BATTERY_LOW"

LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_CRITICAL = "CRITICAL"

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_CENT = Decimal("0.01")

# Order of events that share a timestamp, used by sort_events().
_EVENT_ORDER = {EVENT_MODE_SWITCH: 0, EVENT_OVERLOAD: 1, EVENT_BATTERY_LOW: 2}


# --- Input normalisation -----------------------------------------------------
def parse_timestamp(ts) -> datetime:
    """Accept 'YYYY-MM-DD HH:MM:SS' (or ISO 8601) strings, datetime or pandas.Timestamp.

    The hour is the wall-clock hour as written; time zones are not converted.
    """
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        text = ts.strip()
        if text.endswith(("Z", "z")):  # fromisoformat rejects 'Z' before Python 3.11
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"unparseable timestamp: {ts!r}") from exc
    else:
        raise ValueError(f"unsupported timestamp type {type(ts).__name__}: {ts!r}")
    if not isinstance(dt.hour, int):  # pandas.NaT is a datetime subclass with hour == nan
        raise ValueError(f"invalid timestamp: {ts!r}")
    return dt


def format_timestamp(ts) -> str:
    """Normalise any accepted timestamp to 'YYYY-MM-DD HH:MM:SS'."""
    return parse_timestamp(ts).strftime(TIMESTAMP_FORMAT)


def _to_decimal(value) -> Decimal:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"predicted_kw is not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"predicted_kw is not finite: {value!r}")
    return Decimal(repr(number))  # shortest repr: 160.005 stays 160.005, not 160.00499...


def round_kw(value) -> float:
    """Round to 2 decimals, halves away from zero (160.005 -> 160.01, 199.995 -> 200.0)."""
    return float(_to_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))


# --- Rules -------------------------------------------------------------------
def classify_hour(predicted_kw, timestamp) -> dict:
    """Return {grid_mode, mode_reason, overload_alert} for one forecast hour."""
    kw = _to_decimal(predicted_kw).quantize(_CENT, rounding=ROUND_HALF_UP)
    hour = parse_timestamp(timestamp).hour

    over_demand = kw > STORAGE_THRESHOLD_KW
    in_evening = EVENING_START_HOUR <= hour <= EVENING_END_HOUR

    if over_demand and in_evening:
        reason = REASON_BOTH
    elif over_demand:
        reason = REASON_DEMAND
    elif in_evening:
        reason = REASON_EVENING
    else:
        reason = REASON_NORMAL

    return {
        "grid_mode": RENEWABLE_STORAGE if reason != REASON_NORMAL else MAIN_GRID,
        "mode_reason": reason,
        "overload_alert": kw >= OVERLOAD_THRESHOLD_KW,
    }


def apply_rules(hours) -> list:
    """Return new hour dicts with predicted_kw rounded and the three rule fields added.

    Each input dict needs 'timestamp' and 'predicted_kw'. Inputs are not mutated.
    """
    result = []
    for index, hour in enumerate(hours):
        try:
            kw = round_kw(hour["predicted_kw"])
            decision = classify_hour(kw, hour["timestamp"])
        except KeyError as exc:
            raise ValueError(f"hour {index}: missing field {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"hour {index}: {exc}") from exc
        result.append({**hour, "predicted_kw": kw, **decision})
    return result


def detect_events(hours, initial_mode=None) -> list:
    """MODE_SWITCH on every grid_mode change and OVERLOAD for every overload hour.

    The first hour has no predecessor, so it raises no MODE_SWITCH unless
    initial_mode (the mode before the window, e.g. from the previous forecast) is given.
    Hours that already carry grid_mode / mode_reason / overload_alert are used as is;
    otherwise they are classified from predicted_kw.
    """
    events = []
    previous = initial_mode
    for hour in hours:
        timestamp = format_timestamp(hour["timestamp"])
        decision = hour if _has_decision(hour) else classify_hour(hour["predicted_kw"], hour["timestamp"])
        mode = decision["grid_mode"]

        if previous is not None and mode != previous:
            events.append({
                "timestamp": timestamp,
                "type": EVENT_MODE_SWITCH,
                "level": LEVEL_INFO,
                "message": f"{previous} -> {mode} ({decision['mode_reason']})",
            })
        previous = mode

        if decision["overload_alert"]:
            events.append({
                "timestamp": timestamp,
                "type": EVENT_OVERLOAD,
                "level": LEVEL_CRITICAL,
                "message": (f"Critical overload: predicted {round_kw(hour['predicted_kw']):.2f} kW "
                            f">= {OVERLOAD_THRESHOLD_KW} kW"),
            })
    return events


def sort_events(*event_lists) -> list:
    """Merge event lists chronologically; ties go MODE_SWITCH, OVERLOAD, BATTERY_LOW."""
    merged = [event for events in event_lists for event in events]
    return sorted(merged, key=lambda e: (e["timestamp"], _EVENT_ORDER.get(e["type"], 99)))


def summarize(hours) -> dict:
    """The contract's `summary` block, derived from hours that went through the rules (and battery).

    peak_kw / peak_timestamp: first hour with the highest predicted_kw (None when empty).
    min_soc_pct: lowest battery_soc_pct, or None when the battery has not been simulated.
    """
    hours = list(hours)
    peak = max(hours, key=lambda h: h["predicted_kw"], default=None)  # max() keeps the first tie
    socs = [h["battery_soc_pct"] for h in hours if h.get("battery_soc_pct") is not None]
    return {
        "peak_kw": round_kw(peak["predicted_kw"]) if peak else None,
        "peak_timestamp": format_timestamp(peak["timestamp"]) if peak else None,
        "storage_hours": sum(1 for h in hours if h["grid_mode"] == RENEWABLE_STORAGE),
        "main_grid_hours": sum(1 for h in hours if h["grid_mode"] == MAIN_GRID),
        "overload_hours": sum(1 for h in hours if h["overload_alert"]),
        "min_soc_pct": min(socs) if socs else None,
    }


def _has_decision(hour) -> bool:
    return all(key in hour for key in ("grid_mode", "mode_reason", "overload_alert"))

"""Battery state-of-charge simulation for the forecast window.

This model is our own assumption (the brief does not define one). Change the
constants below to tune it; nothing else in the repo hard-codes them.

Per forecast hour (each row is one hour):
    RENEWABLE_STORAGE hour: battery discharges predicted_kw x 1 h
    MAIN_GRID hour:         battery charges from the grid at GRID_CHARGE_KW
    every hour:             solar charges  solar_irradiance_wm2 / 1000 x SOLAR_ARRAY_KW
The net energy is applied once and SoC is then clamped to 0-100 %. battery_soc_pct
is the state at the END of the hour. battery_low = SoC < LOW_SOC_PCT; it only raises
a warning and never changes grid_mode.
"""
from __future__ import annotations

import math

try:  # imported as a package (backend.battery) or from inside backend/
    from .controller import (EVENT_BATTERY_LOW, LEVEL_WARN, MAIN_GRID, RENEWABLE_STORAGE,
                             classify_hour, format_timestamp, round_kw)
except ImportError:
    from controller import (EVENT_BATTERY_LOW, LEVEL_WARN, MAIN_GRID, RENEWABLE_STORAGE,
                            classify_hour, format_timestamp, round_kw)

# --- Tunable constants -------------------------------------------------------
CAPACITY_KWH = 2000.0
INITIAL_SOC_PCT = 90.0
LOW_SOC_PCT = 20.0
MIN_SOC_PCT = 0.0
MAX_SOC_PCT = 100.0
GRID_CHARGE_KW = 150.0       # charge rate while on MAIN_GRID ("up to" this; the clamp caps it)
SOLAR_ARRAY_KW = 200.0       # array output at 1000 W/m2
FULL_SUN_WM2 = 1000.0
STEP_HOURS = 1.0


def _finite(value, default=0.0) -> float:
    """Missing / NaN / infinite values count as `default` (no free energy, no demand)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _low_event(timestamp: str, soc_pct: float) -> dict:
    return {
        "timestamp": timestamp,
        "type": EVENT_BATTERY_LOW,
        "level": LEVEL_WARN,
        "message": f"Battery low: state of charge {soc_pct:.2f}% is below {LOW_SOC_PCT:g}%",
    }


def detect_low_events(hours) -> list:
    """Re-derive the BATTERY_LOW events from hours that already carry battery_low / battery_soc_pct.

    Same rule as simulate(): one event each time battery_low goes from False to True.
    Used to rebuild events for a stored forecast.
    """
    events, was_low = [], False
    for hour in hours:
        low = bool(hour["battery_low"])
        if low and not was_low:
            events.append(_low_event(format_timestamp(hour["timestamp"]), hour["battery_soc_pct"]))
        was_low = low
    return events


def simulate(hours, initial_soc_pct: float = INITIAL_SOC_PCT):
    """Add battery_soc_pct and battery_low to each hour.

    Returns (new_hours, events). Inputs are not mutated. Each hour needs 'timestamp'
    and 'predicted_kw'; it uses the hour's own grid_mode, or classifies it when absent.
    Missing solar counts as 0, negative solar as 0, negative demand as 0.

    A BATTERY_LOW event (level WARN) is emitted each time SoC crosses from at/above
    LOW_SOC_PCT to below it, i.e. once per low spell, not once per low hour. If the
    window starts below the threshold the event fires on the first hour.
    """
    soc = min(max(float(initial_soc_pct), MIN_SOC_PCT), MAX_SOC_PCT)
    was_low = False
    result, events = [], []

    for index, hour in enumerate(hours):
        try:
            mode = hour.get("grid_mode") or classify_hour(hour["predicted_kw"], hour["timestamp"])["grid_mode"]
            timestamp = format_timestamp(hour["timestamp"])
        except KeyError as exc:
            raise ValueError(f"hour {index}: missing field {exc}") from exc

        solar_kw = max(0.0, _finite(hour.get("solar_irradiance_wm2"))) / FULL_SUN_WM2 * SOLAR_ARRAY_KW
        if mode == RENEWABLE_STORAGE:
            demand_kw = _finite(hour["predicted_kw"])
            net_kwh = (solar_kw - max(0.0, demand_kw)) * STEP_HOURS
        elif mode == MAIN_GRID:
            net_kwh = (GRID_CHARGE_KW + solar_kw) * STEP_HOURS
        else:
            raise ValueError(f"hour {index}: unknown grid_mode {mode!r}")

        soc = min(max(soc + net_kwh / CAPACITY_KWH * 100.0, MIN_SOC_PCT), MAX_SOC_PCT)

        shown = round_kw(soc)  # same half-up 2-decimal rounding as the kW values
        low = shown < LOW_SOC_PCT  # judged on the displayed value so number and flag agree
        if low and not was_low:
            events.append(_low_event(timestamp, shown))
        was_low = low

        result.append({**hour, "battery_soc_pct": shown, "battery_low": low})

    return result, events

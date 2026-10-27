import math

import pytest

import battery
from battery import (CAPACITY_KWH, GRID_CHARGE_KW, INITIAL_SOC_PCT, LOW_SOC_PCT, SOLAR_ARRAY_KW,
                     detect_low_events, simulate)
from controller import MAIN_GRID, RENEWABLE_STORAGE, apply_rules, classify_hour, detect_events


def at(hour, day="2015-06-16"):
    return f"{day} {hour:02d}:00:00"


def hour(h, kw, solar=0.0, day="2015-06-16"):
    return {"timestamp": at(h, day), "predicted_kw": kw, "solar_irradiance_wm2": solar}


def run(rows, **kwargs):
    return simulate(apply_rules(rows), **kwargs)


def pct(kwh):
    return kwh / CAPACITY_KWH * 100.0


# --- Model constants -------------------------------------------------------------
def test_constants_match_the_contract():
    assert CAPACITY_KWH == 2000
    assert INITIAL_SOC_PCT == 90
    assert LOW_SOC_PCT == 20
    assert GRID_CHARGE_KW == 150
    assert SOLAR_ARRAY_KW == 200
    assert battery.MIN_SOC_PCT == 0 and battery.MAX_SOC_PCT == 100


# --- Single-hour arithmetic ---------------------------------------------------------
def test_main_grid_hour_charges_150_kwh():
    out, events = run([hour(10, 100.0)])
    assert out[0]["grid_mode"] == MAIN_GRID
    assert out[0]["battery_soc_pct"] == pytest.approx(90 + pct(150))  # 97.5
    assert events == []


def test_main_grid_hour_adds_solar_on_top_of_grid_charge():
    out, _ = run([hour(10, 100.0, solar=500.0)], initial_soc_pct=50)
    assert out[0]["battery_soc_pct"] == pytest.approx(50 + pct(150 + 100))  # 500/1000*200 = 100 kW


def test_storage_hour_discharges_predicted_kw():
    out, _ = run([hour(10, 180.0)])
    assert out[0]["grid_mode"] == RENEWABLE_STORAGE
    assert out[0]["battery_soc_pct"] == pytest.approx(90 - pct(180))  # 81.0


def test_storage_hour_with_solar_nets_the_two():
    out, _ = run([hour(10, 180.0, solar=1000.0)])  # +200 kW solar, -180 kW load
    assert out[0]["battery_soc_pct"] == pytest.approx(90 + pct(20))


def test_evening_hour_discharges_even_when_demand_is_low():
    out, _ = run([hour(19, 100.0)])
    assert out[0]["grid_mode"] == RENEWABLE_STORAGE
    assert out[0]["battery_soc_pct"] == pytest.approx(90 - pct(100))


def test_solar_scales_linearly_with_irradiance():
    for solar, kw in [(0, 0), (250, 50), (1000, 200), (169, 33.8)]:
        out, _ = run([hour(19, 100.0, solar=solar)], initial_soc_pct=50)
        assert out[0]["battery_soc_pct"] == pytest.approx(50 + pct(kw - 100), abs=0.005)


# --- Three-hour hand-computed sequence ---------------------------------------------------
def test_hand_computed_sequence_carries_state_between_hours():
    rows = [
        hour(16, 150.0, solar=300.0),   # MAIN: +150 +60  -> 90 + 10.5     = 100.5 -> clamp 100
        hour(17, 100.0, solar=100.0),   # MAIN: +150 +20, already full      = 100 (clamped)
        hour(18, 130.0, solar=0.0),     # STORAGE (evening): -130           = 93.5
        hour(19, 170.0, solar=100.0),   # STORAGE: -170 +20 = -150          = 86.0
    ]
    out, events = run(rows)
    assert [h["battery_soc_pct"] for h in out] == [100.0, 100.0, 93.5, 86.0]
    assert [h["battery_low"] for h in out] == [False] * 4
    assert events == []


def test_soc_is_end_of_hour_and_carries_unrounded_state():
    # 3 x -0.123456 kWh-ish steps: rounding each step would drift; internal state must not.
    rows = [hour(19, 0.0, solar=0.0)] * 1
    out, _ = run(rows, initial_soc_pct=50.123456789)
    assert out[0]["battery_soc_pct"] == 50.12


# --- Clamping ---------------------------------------------------------------------------
def test_soc_clamps_at_100_and_stays_there():
    rows = [hour(h, 100.0, solar=1000.0) for h in range(0, 10)]  # all MAIN_GRID, +350 kWh/h
    out, _ = run(rows)
    socs = [h["battery_soc_pct"] for h in out]
    assert max(socs) == 100.0
    assert socs[-1] == 100.0
    assert all(s <= 100.0 for s in socs)
    assert socs[0] == 100.0  # 90 + 17.5 clamps immediately


def test_soc_never_exceeds_100_from_a_full_start():
    out, _ = run([hour(10, 100.0, solar=1000.0)], initial_soc_pct=100)
    assert out[0]["battery_soc_pct"] == 100.0


def test_soc_clamps_at_0_and_stays_there():
    rows = [hour(h, 300.0) for h in range(0, 8)]  # all STORAGE, -300 kWh/h = -15%/h
    out, _ = run(rows, initial_soc_pct=30)
    assert [h["battery_soc_pct"] for h in out] == [15.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert all(h["battery_soc_pct"] >= 0.0 for h in out)


def test_soc_recovers_from_zero():
    # 10:00 STORAGE empties it (10% -> 0); 11:00 and 12:00 are MAIN_GRID, +150 kWh = +7.5% each.
    out, _ = run([hour(10, 300.0), hour(11, 100.0), hour(12, 100.0)], initial_soc_pct=10)
    assert [h["battery_soc_pct"] for h in out] == [0.0, 7.5, 15.0]


@pytest.mark.parametrize("start, expected", [(-50, 0.0), (0, 0.0), (100, 100.0), (250, 100.0)])
def test_initial_soc_is_clamped(start, expected):
    # zero net change: STORAGE at 200 kW with 1000 W/m2 solar (+200 kW)
    out, _ = run([hour(19, 200.0, solar=1000.0)], initial_soc_pct=start)
    assert out[0]["battery_soc_pct"] == expected


# --- battery_low ------------------------------------------------------------------------
def test_exactly_20_percent_is_not_low():
    out, events = run([hour(19, 200.0, solar=1000.0)], initial_soc_pct=20.0)
    assert out[0]["battery_soc_pct"] == 20.0
    assert out[0]["battery_low"] is False
    assert events == []


def test_just_below_20_is_low():
    out, events = run([hour(19, 200.0, solar=1000.0)], initial_soc_pct=19.99)
    assert out[0]["battery_low"] is True
    assert len(events) == 1


def test_low_threshold_is_judged_on_the_displayed_value():
    # 19.996 displays as 20.00, so it is not low; 19.994 displays as 19.99, so it is.
    out, _ = run([hour(19, 200.0, solar=1000.0)], initial_soc_pct=19.996)
    assert out[0]["battery_soc_pct"] == 20.0 and out[0]["battery_low"] is False
    out, _ = run([hour(19, 200.0, solar=1000.0)], initial_soc_pct=19.994)
    assert out[0]["battery_soc_pct"] == 19.99 and out[0]["battery_low"] is True


def test_battery_low_event_fires_once_for_a_long_low_spell():
    rows = [hour(h, 250.0) for h in range(8, 20)]  # -12.5 % per hour, all STORAGE
    out, events = run(rows)
    lows = [h["battery_low"] for h in out]
    socs = [h["battery_soc_pct"] for h in out]
    # 90 -> 77.5 -> 65 -> 52.5 -> 40 -> 27.5 -> 15 (first low) -> 2.5 -> 0 ...
    assert socs[:8] == [77.5, 65.0, 52.5, 40.0, 27.5, 15.0, 2.5, 0.0]
    assert lows == [False] * 5 + [True] * 7
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "BATTERY_LOW"
    assert event["level"] == "WARN"
    assert event["timestamp"] == at(13)  # the sixth hour, 08:00 + 5
    assert "15.00%" in event["message"] and "20%" in event["message"]


def test_battery_low_event_fires_again_after_recovery():
    rows = (
        [hour(h, 300.0) for h in (9, 10, 11)]            # 90 -> 75 -> 60 -> 45 (STORAGE)
        + [hour(12, 300.0), hour(13, 300.0)]              # 30 -> 15  low #1 at 13:00
        + [hour(14, 100.0, solar=1000.0)] * 1             # 100 kW MAIN: +150 +200 -> 32.5, recovered
        + [hour(15, 300.0), hour(16, 300.0)]              # 17.5 low #2 at 15:00... (see asserts)
    )
    out, events = run(rows)
    socs = [h["battery_soc_pct"] for h in out]
    assert socs == [75.0, 60.0, 45.0, 30.0, 15.0, 32.5, 17.5, 2.5]
    assert [h["battery_low"] for h in out] == [False, False, False, False, True, False, True, True]
    assert [e["timestamp"] for e in events] == [at(13), at(15)]


def test_starting_below_threshold_warns_on_the_first_hour():
    out, events = run([hour(19, 200.0, solar=1000.0), hour(20, 200.0, solar=1000.0)], initial_soc_pct=10)
    assert [h["battery_low"] for h in out] == [True, True]
    assert [e["timestamp"] for e in events] == [at(19)]


def test_no_event_when_battery_never_gets_low():
    out, events = run([hour(h, 100.0) for h in range(0, 24)])
    assert not any(h["battery_low"] for h in out)
    assert events == []


def test_soc_stuck_at_zero_reports_one_event():
    out, events = run([hour(h, 300.0) for h in range(0, 12)], initial_soc_pct=5)
    assert len(events) == 1 and events[0]["timestamp"] == at(0)
    assert all(h["battery_low"] for h in out)


# --- The battery never changes grid_mode ------------------------------------------------------
def test_battery_never_changes_grid_mode_or_other_rule_fields():
    # Mixed day: evening hours and 170+ kW hours drain, the rest charge.
    rows = [hour(h, 170.0 if h % 3 == 0 else 100.0, solar=max(0.0, 800.0 - abs(h - 12) * 120))
            for h in range(24)]
    ruled = apply_rules(rows)
    out, _ = simulate(ruled, initial_soc_pct=2)  # battery empty almost from the start
    for before, after in zip(ruled, out):
        for key in ("grid_mode", "mode_reason", "overload_alert", "predicted_kw", "timestamp"):
            assert before[key] == after[key]
    assert any(h["battery_soc_pct"] == 0.0 for h in out)
    assert any(h["grid_mode"] == RENEWABLE_STORAGE and h["battery_soc_pct"] == 0.0 for h in out)


def test_empty_battery_still_discharges_in_storage_mode_decision():
    out, _ = run([hour(19, 150.0)], initial_soc_pct=0)
    assert out[0]["grid_mode"] == RENEWABLE_STORAGE and out[0]["battery_soc_pct"] == 0.0
    assert out[0]["battery_low"] is True


def test_simulate_uses_provided_grid_mode_and_classifies_when_absent():
    raw = [hour(19, 100.0)]
    from_raw, _ = simulate(raw)
    from_ruled, _ = simulate(apply_rules(raw))
    assert from_raw[0]["battery_soc_pct"] == from_ruled[0]["battery_soc_pct"]
    assert "grid_mode" not in from_raw[0]  # simulate adds only its own two fields


# --- Hygiene ----------------------------------------------------------------------------------
def test_output_fields_and_order_preserved():
    rows = [hour(h, 120.0) for h in (5, 3, 9)]
    out, _ = run(rows)
    assert [h["timestamp"] for h in out] == [at(5), at(3), at(9)]
    assert all({"battery_soc_pct", "battery_low"} <= set(h) for h in out)
    assert all(isinstance(h["battery_low"], bool) for h in out)


def test_simulate_does_not_mutate_input():
    ruled = apply_rules([hour(19, 150.0, solar=10.0)])
    snapshot = [dict(h) for h in ruled]
    out, _ = simulate(ruled)
    assert ruled == snapshot
    assert out[0] is not ruled[0]


def test_empty_input():
    assert simulate([]) == ([], [])


@pytest.mark.parametrize("solar", [None, float("nan"), float("inf"), "n/a", -300.0])
def test_missing_or_bad_solar_counts_as_zero(solar):
    with_bad, _ = run([hour(10, 100.0, solar=solar)])
    without, _ = run([hour(10, 100.0, solar=0.0)])
    assert with_bad[0]["battery_soc_pct"] == without[0]["battery_soc_pct"]


def test_missing_solar_key_counts_as_zero():
    row = {"timestamp": at(10), "predicted_kw": 100.0}
    out, _ = run([row])
    assert out[0]["battery_soc_pct"] == pytest.approx(90 + pct(150))


def test_missing_fields_report_the_hour():
    with pytest.raises(ValueError, match="hour 1"):
        simulate([{**apply_rules([hour(1, 100.0)])[0]}, {"predicted_kw": 100.0, "grid_mode": MAIN_GRID}])


def test_unknown_grid_mode_is_rejected():
    with pytest.raises(ValueError, match="grid_mode"):
        simulate([{**hour(10, 100.0), "grid_mode": "SOMETHING"}])


def test_nan_demand_is_rejected_by_the_rules_before_the_battery():
    with pytest.raises(ValueError):
        simulate([hour(10, float("nan"))])


def test_events_merge_cleanly_with_controller_events():
    from controller import sort_events
    rows = [hour(h, 250.0) for h in range(8, 14)]
    ruled = apply_rules(rows)
    out, battery_events = simulate(ruled)
    merged = sort_events(detect_events(out, initial_mode=MAIN_GRID), battery_events)
    types = [e["type"] for e in merged]
    assert types.count("MODE_SWITCH") == 1 and types.count("BATTERY_LOW") == 1
    assert types.count("OVERLOAD") == 6
    assert math.isclose(out[-1]["battery_soc_pct"], 15.0)
    # at 08:00 the order is MODE_SWITCH then OVERLOAD
    assert [e["type"] for e in merged[:2]] == ["MODE_SWITCH", "OVERLOAD"]


# --- Realistic day (mirrors the dashboard's demo flow) -----------------------------------------------
def test_full_day_end_to_end_invariants():
    solar_by_hour = [max(0.0, 900.0 * math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0.0
                     for h in range(24)]
    kw_by_hour = [120 + 60 * math.sin(math.pi * (h - 8) / 12) + (40 if 18 <= h <= 21 else 0) for h in range(24)]
    rows = [hour(h, kw_by_hour[h], solar=solar_by_hour[h]) for h in range(24)]
    ruled = apply_rules(rows)
    out, events = simulate(ruled)
    assert len(out) == 24
    for h in out:
        assert 0.0 <= h["battery_soc_pct"] <= 100.0
        assert h["battery_low"] == (h["battery_soc_pct"] < LOW_SOC_PCT)
        assert classify_hour(h["predicted_kw"], h["timestamp"])["grid_mode"] == h["grid_mode"]
    lows = [h["battery_low"] for h in out]
    crossings = sum(1 for prev, cur in zip([False] + lows, lows) if cur and not prev)
    assert len(events) == crossings


# --- detect_low_events (rebuilds events for stored forecasts) ------------------------------------
@pytest.mark.parametrize("rows, start", [
    ([hour(h, 250.0) for h in range(8, 20)], 90.0),                       # one long low spell
    ([hour(h, 300.0) for h in (9, 10, 11, 12, 13)] + [hour(14, 100.0, solar=1000.0)]
     + [hour(15, 300.0), hour(16, 300.0)], 90.0),                          # low, recover, low again
    ([hour(19, 200.0, solar=1000.0), hour(20, 200.0, solar=1000.0)], 10.0),  # starts low
    ([hour(h, 100.0) for h in range(24)], 90.0),                           # never low
    ([], 90.0),
])
def test_detect_low_events_reproduces_simulate(rows, start):
    out, events = run(rows, initial_soc_pct=start)
    assert detect_low_events(out) == events

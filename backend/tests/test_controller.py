from datetime import datetime

import pytest

from controller import (MAIN_GRID, RENEWABLE_STORAGE, apply_rules, classify_hour,
                        detect_events, format_timestamp, parse_timestamp, round_kw,
                        sort_events, summarize)

DAY = "2015-06-16"


def at(hour, day=DAY, minute=0):
    return f"{day} {hour:02d}:{minute:02d}:00"


# --- Demand threshold: > 160 kW -> storage -------------------------------------
@pytest.mark.parametrize("kw, mode, reason", [
    (0.0, MAIN_GRID, "normal"),
    (159.99, MAIN_GRID, "normal"),
    (160.00, MAIN_GRID, "normal"),            # exactly 160 is NOT over 160
    (160.004, MAIN_GRID, "normal"),           # rounds to 160.00
    (160.005, RENEWABLE_STORAGE, "demand_over_160"),  # half rounds up to 160.01
    (160.01, RENEWABLE_STORAGE, "demand_over_160"),
    (160.1, RENEWABLE_STORAGE, "demand_over_160"),
    (306.0, RENEWABLE_STORAGE, "demand_over_160"),
])
def test_demand_threshold_outside_evening(kw, mode, reason):
    result = classify_hour(kw, at(12))
    assert result["grid_mode"] == mode
    assert result["mode_reason"] == reason


# --- Overload threshold: >= 200 kW ---------------------------------------------
@pytest.mark.parametrize("kw, alert", [
    (199.98, False),
    (199.99, False),
    (199.994, False),                         # rounds to 199.99
    (199.995, True),                          # half rounds up to 200.00
    (200.00, True),                           # exactly 200 alerts
    (200.01, True),
    (231.5, True),
])
def test_overload_threshold(kw, alert):
    assert classify_hour(kw, at(12))["overload_alert"] is alert


@pytest.mark.parametrize("hour", [3, 12, 18, 20, 22, 23])
def test_overload_is_independent_of_grid_mode(hour):
    low = classify_hour(150.0, at(hour))
    high = classify_hour(250.0, at(hour))
    assert low["overload_alert"] is False
    assert high["overload_alert"] is True
    # the mode is decided by the storage rules only
    assert high["grid_mode"] == RENEWABLE_STORAGE


def test_storage_without_alert_and_storage_with_alert():
    # 180 kW: storage, no alert. 200 kW: storage AND alert (200 > 160, so alert implies storage).
    assert classify_hour(180.0, at(12)) == {
        "grid_mode": RENEWABLE_STORAGE, "mode_reason": "demand_over_160", "overload_alert": False}
    assert classify_hour(200.0, at(12)) == {
        "grid_mode": RENEWABLE_STORAGE, "mode_reason": "demand_over_160", "overload_alert": True}


# --- Evening window 18:00-22:00 inclusive --------------------------------------
@pytest.mark.parametrize("hour, in_window", [
    (0, False), (1, False), (12, False), (16, False),
    (17, False),                              # 17:00 outside
    (18, True),                               # 18:00 inside
    (19, True), (20, True), (21, True),
    (22, True),                               # 22:00 inside
    (23, False),                              # 23:00 outside
])
def test_evening_window_hours_with_low_demand(hour, in_window):
    result = classify_hour(100.0, at(hour))
    if in_window:
        assert result["grid_mode"] == RENEWABLE_STORAGE
        assert result["mode_reason"] == "evening_window"
    else:
        assert result["grid_mode"] == MAIN_GRID
        assert result["mode_reason"] == "normal"


@pytest.mark.parametrize("minute", [0, 1, 30, 59])
def test_minutes_do_not_move_the_window(minute):
    assert classify_hour(100.0, at(17, minute=minute))["grid_mode"] == MAIN_GRID
    assert classify_hour(100.0, at(18, minute=minute))["grid_mode"] == RENEWABLE_STORAGE
    assert classify_hour(100.0, at(22, minute=minute))["grid_mode"] == RENEWABLE_STORAGE
    assert classify_hour(100.0, at(23, minute=minute))["grid_mode"] == MAIN_GRID


def test_midnight_is_main_grid_and_next_day_resets():
    assert classify_hour(100.0, "2015-06-17 00:00:00")["grid_mode"] == MAIN_GRID
    assert classify_hour(100.0, "2015-06-16 00:00:00")["grid_mode"] == MAIN_GRID


# --- mode_reason: all four values ----------------------------------------------
@pytest.mark.parametrize("kw, hour, reason", [
    (100.0, 12, "normal"),
    (160.0, 17, "normal"),
    (161.0, 12, "demand_over_160"),
    (161.0, 17, "demand_over_160"),
    (161.0, 23, "demand_over_160"),
    (100.0, 18, "evening_window"),
    (160.0, 20, "evening_window"),            # exactly 160 in the window: only the window
    (160.0, 22, "evening_window"),
    (160.01, 18, "both"),
    (250.0, 22, "both"),
])
def test_mode_reason(kw, hour, reason):
    assert classify_hour(kw, at(hour))["mode_reason"] == reason


# --- Rounding ------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    (160.004, 160.0), (160.005, 160.01), (160.01, 160.01),
    (199.994, 199.99), (199.995, 200.0), (199.996, 200.0),
    (182.414, 182.41), (182.415, 182.42), (0.0, 0.0), (100, 100.0),
    ("182.41", 182.41), (-0.004, 0.0),
])
def test_round_kw_half_up(raw, expected):
    assert round_kw(raw) == expected


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), float("-inf"), "abc", ""])
def test_bad_numbers_are_rejected(bad):
    with pytest.raises(ValueError):
        classify_hour(bad, at(12))
    with pytest.raises(ValueError):
        round_kw(bad)


def test_numpy_floats_are_accepted():
    np = pytest.importorskip("numpy")
    result = classify_hour(np.float64(200.0), at(12))
    assert result["overload_alert"] is True
    assert round_kw(np.float32(160.0)) == 160.0


# --- Timestamp handling ---------------------------------------------------------
def test_string_and_datetime_give_same_result():
    for hour in range(24):
        for kw in (100.0, 160.0, 160.01, 200.0):
            from_str = classify_hour(kw, at(hour))
            from_dt = classify_hour(kw, datetime(2015, 6, 16, hour))
            assert from_str == from_dt


@pytest.mark.parametrize("ts", [
    "2015-06-16 18:00:00", "2015-06-16T18:00:00", "2015-06-16 18:00",
    "2015-06-16T18:00:00Z", "2015-06-16T18:00:00+05:30", "  2015-06-16 18:00:00  ",
    datetime(2015, 6, 16, 18, 0, 0),
])
def test_timestamp_formats(ts):
    assert parse_timestamp(ts).hour == 18
    assert classify_hour(100.0, ts)["grid_mode"] == RENEWABLE_STORAGE
    assert format_timestamp(ts) == "2015-06-16 18:00:00"


def test_pandas_timestamp_and_nat():
    pd = pytest.importorskip("pandas")
    assert classify_hour(100.0, pd.Timestamp("2015-06-16 22:00:00"))["grid_mode"] == RENEWABLE_STORAGE
    assert classify_hour(100.0, pd.Timestamp("2015-06-16 23:00:00"))["grid_mode"] == MAIN_GRID
    with pytest.raises(ValueError):
        classify_hour(100.0, pd.NaT)


@pytest.mark.parametrize("bad", [None, "", "not a date", "2015-13-45 00:00:00", 12, 1.5])
def test_bad_timestamps_are_rejected(bad):
    with pytest.raises(ValueError):
        classify_hour(100.0, bad)


# --- apply_rules ----------------------------------------------------------------
def test_apply_rules_adds_fields_rounds_and_keeps_extras():
    hours = [{"timestamp": at(18), "predicted_kw": 160.004, "ambient_temp_c": 30.0}]
    out = apply_rules(hours)
    assert out == [{
        "timestamp": at(18), "predicted_kw": 160.0, "ambient_temp_c": 30.0,
        "grid_mode": RENEWABLE_STORAGE, "mode_reason": "evening_window", "overload_alert": False,
    }]


def test_apply_rules_does_not_mutate_input():
    hours = [{"timestamp": at(12), "predicted_kw": 199.995}]
    snapshot = [dict(h) for h in hours]
    out = apply_rules(hours)
    assert hours == snapshot
    assert out[0] is not hours[0]


def test_apply_rules_displayed_value_and_badge_agree():
    # What is shown (predicted_kw in the output) must reproduce the badge exactly.
    for raw in (159.995, 160.004, 160.005, 199.994, 199.995, 200.004):
        out = apply_rules([{"timestamp": at(12), "predicted_kw": raw}])[0]
        shown = out["predicted_kw"]
        assert out["grid_mode"] == (RENEWABLE_STORAGE if shown > 160 else MAIN_GRID)
        assert out["overload_alert"] is (shown >= 200)


def test_apply_rules_preserves_order_and_length():
    hours = [{"timestamp": at(h), "predicted_kw": 100.0 + h} for h in (5, 3, 9, 1)]
    out = apply_rules(hours)
    assert [h["timestamp"] for h in out] == [at(5), at(3), at(9), at(1)]


def test_apply_rules_empty():
    assert apply_rules([]) == []


def test_apply_rules_reports_which_hour_is_bad():
    hours = [{"timestamp": at(1), "predicted_kw": 100.0}, {"timestamp": at(2)}]
    with pytest.raises(ValueError, match="hour 1"):
        apply_rules(hours)
    hours = [{"timestamp": at(1), "predicted_kw": float("nan")}]
    with pytest.raises(ValueError, match="hour 0"):
        apply_rules(hours)


# --- A full 24-hour day with known answers ---------------------------------------
def day_profile():
    """Demand per hour of 2015-06-16 and the expected (mode, reason, alert)."""
    demand = {h: 140.0 for h in range(24)}
    for h in range(9, 15):
        demand[h] = 170.0                     # 09-14: over 160
    demand[17] = 100.0
    for h in range(18, 23):
        demand[h] = 150.0                     # 18-22: evening window, demand low
    demand[20] = 210.0                        # 20: both + overload
    demand[23] = 150.0
    return demand


def expected_for(hour, kw):
    over, evening = kw > 160, 18 <= hour <= 22
    reason = "both" if over and evening else "demand_over_160" if over else \
        "evening_window" if evening else "normal"
    return (RENEWABLE_STORAGE if over or evening else MAIN_GRID), reason, kw >= 200


def build_day(profile=None):
    profile = profile or day_profile()
    return apply_rules([{"timestamp": at(h), "predicted_kw": profile[h]} for h in range(24)])


def test_24_hour_sequence_modes():
    out = build_day()
    assert len(out) == 24
    modes = [h["grid_mode"] for h in out]
    assert modes == (
        [MAIN_GRID] * 9                       # 00-08
        + [RENEWABLE_STORAGE] * 6             # 09-14 demand
        + [MAIN_GRID] * 3                     # 15-17
        + [RENEWABLE_STORAGE] * 5             # 18-22 evening
        + [MAIN_GRID]                         # 23
    )
    assert out[20]["mode_reason"] == "both"
    assert [h["mode_reason"] for h in out[18:23]] == [
        "evening_window", "evening_window", "both", "evening_window", "evening_window"]
    for h in out:
        hour = int(h["timestamp"][11:13])
        assert (h["grid_mode"], h["mode_reason"], h["overload_alert"]) == expected_for(hour, h["predicted_kw"])
    assert sum(h["grid_mode"] == RENEWABLE_STORAGE for h in out) == 11
    assert sum(h["grid_mode"] == MAIN_GRID for h in out) == 13


def test_24_hour_sequence_events():
    events = detect_events(build_day())
    assert [(e["timestamp"], e["type"], e["message"]) for e in events] == [
        (at(9), "MODE_SWITCH", "MAIN_GRID -> RENEWABLE_STORAGE (demand_over_160)"),
        (at(15), "MODE_SWITCH", "RENEWABLE_STORAGE -> MAIN_GRID (normal)"),
        (at(18), "MODE_SWITCH", "MAIN_GRID -> RENEWABLE_STORAGE (evening_window)"),
        (at(20), "OVERLOAD", "Critical overload: predicted 210.00 kW >= 200 kW"),
        (at(23), "MODE_SWITCH", "RENEWABLE_STORAGE -> MAIN_GRID (normal)"),
    ]
    assert [e["level"] for e in events] == ["INFO", "INFO", "INFO", "CRITICAL", "INFO"]


def test_reason_change_inside_storage_is_not_a_switch():
    # 17:00 over 160 (storage), 18:00 evening only (still storage): no MODE_SWITCH at 18.
    hours = apply_rules([
        {"timestamp": at(16), "predicted_kw": 100.0},
        {"timestamp": at(17), "predicted_kw": 170.0},
        {"timestamp": at(18), "predicted_kw": 150.0},
        {"timestamp": at(19), "predicted_kw": 100.0},
    ])
    events = detect_events(hours)
    assert [(e["timestamp"], e["type"]) for e in events] == [(at(17), "MODE_SWITCH")]


def test_first_hour_has_no_switch_unless_initial_mode_given():
    hours = apply_rules([{"timestamp": at(18), "predicted_kw": 100.0}])
    assert detect_events(hours) == []
    events = detect_events(hours, initial_mode=MAIN_GRID)
    assert len(events) == 1 and events[0]["message"] == "MAIN_GRID -> RENEWABLE_STORAGE (evening_window)"
    assert detect_events(hours, initial_mode=RENEWABLE_STORAGE) == []


def test_sequence_across_midnight_and_day_boundary():
    hours = apply_rules([
        {"timestamp": "2015-06-16 21:00:00", "predicted_kw": 100.0},
        {"timestamp": "2015-06-16 22:00:00", "predicted_kw": 100.0},
        {"timestamp": "2015-06-16 23:00:00", "predicted_kw": 100.0},
        {"timestamp": "2015-06-17 00:00:00", "predicted_kw": 100.0},
        {"timestamp": "2015-06-17 18:00:00", "predicted_kw": 100.0},
    ])
    assert [h["grid_mode"] for h in hours] == [
        RENEWABLE_STORAGE, RENEWABLE_STORAGE, MAIN_GRID, MAIN_GRID, RENEWABLE_STORAGE]
    events = detect_events(hours)
    assert [(e["timestamp"], e["message"]) for e in events] == [
        ("2015-06-16 23:00:00", "RENEWABLE_STORAGE -> MAIN_GRID (normal)"),
        ("2015-06-17 18:00:00", "MAIN_GRID -> RENEWABLE_STORAGE (evening_window)"),
    ]


def test_flat_sequences_have_no_switch_events():
    steady_main = apply_rules([{"timestamp": at(h), "predicted_kw": 120.0} for h in range(0, 17)])
    assert detect_events(steady_main) == []
    steady_storage = apply_rules([{"timestamp": at(h), "predicted_kw": 180.0} for h in range(24)])
    assert detect_events(steady_storage) == []


def test_every_mode_flip_gives_exactly_one_switch():
    # Alternate 170 / 100 kW across daytime hours: every hour flips the mode.
    hours = apply_rules([{"timestamp": at(h), "predicted_kw": 170.0 if h % 2 else 100.0}
                         for h in range(0, 10)])
    events = detect_events(hours)
    assert len(events) == 9
    assert all(e["type"] == "MODE_SWITCH" for e in events)


def test_overload_event_per_overload_hour():
    hours = apply_rules([
        {"timestamp": at(10), "predicted_kw": 199.99},
        {"timestamp": at(11), "predicted_kw": 200.0},
        {"timestamp": at(12), "predicted_kw": 231.5},
        {"timestamp": at(13), "predicted_kw": 199.0},
    ])
    overloads = [e for e in detect_events(hours) if e["type"] == "OVERLOAD"]
    assert [e["timestamp"] for e in overloads] == [at(11), at(12)]
    assert overloads[1]["message"] == "Critical overload: predicted 231.50 kW >= 200 kW"
    assert {e["level"] for e in overloads} == {"CRITICAL"}


def test_overload_does_not_depend_on_prior_mode():
    # Overload at the very first hour, no switch, still reported.
    hours = apply_rules([{"timestamp": at(2), "predicted_kw": 205.0}])
    assert [e["type"] for e in detect_events(hours)] == ["OVERLOAD"]


def test_detect_events_accepts_raw_hours_and_datetimes():
    raw = [
        {"timestamp": datetime(2015, 6, 16, 17), "predicted_kw": 100.0},
        {"timestamp": datetime(2015, 6, 16, 18), "predicted_kw": 100.0},
    ]
    events = detect_events(raw)
    assert events[0]["timestamp"] == at(18)
    assert events == detect_events(apply_rules(raw))


def test_event_timestamps_are_normalised_strings():
    hours = apply_rules([
        {"timestamp": "2015-06-16T17:00:00", "predicted_kw": 100.0},
        {"timestamp": "2015-06-16T18:00:00", "predicted_kw": 100.0},
    ])
    assert detect_events(hours)[0]["timestamp"] == "2015-06-16 18:00:00"


def test_detect_events_does_not_mutate_input():
    hours = build_day()
    snapshot = [dict(h) for h in hours]
    detect_events(hours)
    assert hours == snapshot


def test_sort_events_orders_by_time_then_type():
    events = sort_events(
        [{"timestamp": at(20), "type": "BATTERY_LOW"}, {"timestamp": at(9), "type": "OVERLOAD"}],
        [{"timestamp": at(20), "type": "OVERLOAD"}, {"timestamp": at(20), "type": "MODE_SWITCH"}],
    )
    assert [(e["timestamp"], e["type"]) for e in events] == [
        (at(9), "OVERLOAD"), (at(20), "MODE_SWITCH"), (at(20), "OVERLOAD"), (at(20), "BATTERY_LOW")]


# --- summarize ---------------------------------------------------------------------------------
def test_summarize_the_known_day():
    summary = summarize(build_day())
    assert summary == {
        "peak_kw": 210.0, "peak_timestamp": at(20),
        "storage_hours": 11, "main_grid_hours": 13, "overload_hours": 1,
        "min_soc_pct": None,  # battery not simulated
    }


def test_summarize_takes_first_peak_on_ties_and_min_soc():
    hours = apply_rules([{"timestamp": at(h), "predicted_kw": kw}
                         for h, kw in ((8, 100.0), (9, 190.0), (10, 190.0), (11, 150.0))])
    for hour, soc in zip(hours, (80.0, 55.5, 70.0, 90.0)):
        hour["battery_soc_pct"] = soc
    summary = summarize(hours)
    assert summary["peak_kw"] == 190.0 and summary["peak_timestamp"] == at(9)
    assert summary["min_soc_pct"] == 55.5


def test_summarize_counts_add_up_and_empty_is_safe():
    day = build_day()
    summary = summarize(day)
    assert summary["storage_hours"] + summary["main_grid_hours"] == len(day)
    assert summarize([]) == {"peak_kw": None, "peak_timestamp": None, "storage_hours": 0,
                             "main_grid_hours": 0, "overload_hours": 0, "min_soc_pct": None}

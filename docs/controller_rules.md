# Transition controller and battery model

Implemented in `backend/controller.py` and `backend/battery.py`; 150+ unit tests in `backend/tests/` cover every
rule below, including each boundary value.

## Grid-switching rules

Each forecast hour is judged on its **predicted demand rounded to 2 decimals** and the **hour of its timestamp**.

| Condition | Result |
|---|---|
| demand **> 160 kW** or hour is **18, 19, 20, 21 or 22** | `RENEWABLE_STORAGE` |
| otherwise (demand <= 160 kW and hour outside 18:00-22:59) | `MAIN_GRID` |
| demand **>= 200 kW** | `overload_alert = true` (critical alert), whatever the grid mode |

The 18:00-22:00 window is inclusive, so it covers the hours 18, 19, 20, 21 and 22 (22:00 to 22:59). The alert is
independent of the mode, but a demand of 200 kW or more is always above 160 kW, so an overloaded hour is always in
storage mode too.

### Why `mode_reason`

Each hour also says *why* it is in its mode, so the dashboard can explain a badge:

| `mode_reason` | Meaning |
|---|---|
| `demand_over_160` | demand above 160 kW, outside the evening window |
| `evening_window` | hour 18-22, demand 160 kW or below |
| `both` | demand above 160 kW **and** hour 18-22 |
| `normal` | neither: `MAIN_GRID` |

### Boundary cases

| Predicted kW | Hour | Rounded kW | Mode | Reason | Overload |
|---|---|---|---|---|---|
| 160.00 | 12:00 | 160.00 | MAIN_GRID | normal | no |
| 160.004 | 12:00 | 160.00 | MAIN_GRID | normal | no |
| 160.005 | 12:00 | 160.01 | RENEWABLE_STORAGE | demand_over_160 | no |
| 160.01 | 12:00 | 160.01 | RENEWABLE_STORAGE | demand_over_160 | no |
| 199.99 | 12:00 | 199.99 | RENEWABLE_STORAGE | demand_over_160 | no |
| 199.994 | 12:00 | 199.99 | RENEWABLE_STORAGE | demand_over_160 | no |
| 199.995 | 12:00 | 200.00 | RENEWABLE_STORAGE | demand_over_160 | **yes** |
| 200.00 | 12:00 | 200.00 | RENEWABLE_STORAGE | demand_over_160 | **yes** |
| 100.00 | 17:00 | 100.00 | MAIN_GRID | normal | no |
| 100.00 | 18:00 | 100.00 | RENEWABLE_STORAGE | evening_window | no |
| 100.00 | 22:00 | 100.00 | RENEWABLE_STORAGE | evening_window | no |
| 100.00 | 23:00 | 100.00 | MAIN_GRID | normal | no |
| 100.00 | 00:00 (midnight) | 100.00 | MAIN_GRID | normal | no |
| 160.00 | 20:00 | 160.00 | RENEWABLE_STORAGE | evening_window | no |
| 160.01 | 18:00 | 160.01 | RENEWABLE_STORAGE | both | no |
| 250.00 | 22:00 | 250.00 | RENEWABLE_STORAGE | both | **yes** |

Minutes do not move the window: 17:59 is outside, 18:00 and 22:59 are inside, 23:00 is outside.

### Rounding

The rules are applied to the value **after rounding to 2 decimals** (halves round up), and the rounded value is the
`predicted_kw` the API returns. So the number on the dashboard and the badge next to it can never disagree:
160.004 shows as 160.00 and is `MAIN_GRID`; 160.005 shows as 160.01 and is `RENEWABLE_STORAGE`. The dashboard
must show `predicted_kw` exactly as the API sends it, without rounding it again.

### Mode-switch events

A `MODE_SWITCH` event is created when an hour's `grid_mode` differs from the previous hour's. A change of
`mode_reason` inside the same mode (for example 17:00 over 160 kW, then 18:00 evening window) is **not** a switch.
The first hour of a forecast has no previous hour, so it raises no switch.

## Event types

| Type | Level | When | Message format |
|---|---|---|---|
| `UPLOAD` | INFO | a forecast is stored | `Forecast f_20261025_101500 generated: 24 hours, model_source=quickml` |
| `MODE_SWITCH` | INFO | grid mode differs from the previous hour | `MAIN_GRID -> RENEWABLE_STORAGE (evening_window)` |
| `OVERLOAD` | CRITICAL | an hour has `overload_alert` | `Critical overload: predicted 231.50 kW >= 200 kW` |
| `BATTERY_LOW` | WARN | state of charge crosses below 20 % | `Battery low: state of charge 15.00% is below 20%` |
| `QUICKML_ERROR` | CRITICAL | QuickML could not be reached (raised by the backend) | free text |

In the system log, `MODE_SWITCH`, `OVERLOAD` and `BATTERY_LOW` messages are prefixed with the forecast hour they
refer to, for example `2015-06-16 18:00:00: MAIN_GRID -> RENEWABLE_STORAGE (evening_window)`, because the log row's
own `time` is when the forecast was made.

## Battery model

The brief asks the dashboard to show battery state of charge but does not define a battery, so this is **our own
simplified model**. Every constant is at the top of `backend/battery.py` and can be tuned.

| Assumption | Value | Reasoning |
|---|---|---|
| Capacity | 2,000 kWh | about 13 hours of the average demand in the training data (157 kW), enough for the 5-hour evening window plus daytime peaks |
| Starting charge | 90 % | a battery that was topped up before the forecast window |
| Low-battery threshold | 20 % | a common reserve so the battery is not run flat |
| Limits | 0 % to 100 % | the state of charge is clamped to the physical range |
| Discharge in `RENEWABLE_STORAGE` hours | predicted kW x 1 h | the storage covers the whole predicted load |
| Charge in `MAIN_GRID` hours | up to 150 kW from the grid | the idle hours are when the battery recharges |
| Solar charging, every hour | irradiance / 1000 x 200 kW | a 200 kW array producing in proportion to irradiance (full output at 1,000 W/m2) |
| Time step | 1 hour per row | the data is hourly |

Per hour, the net energy (discharge or grid charge, plus solar) is added to the stored energy, then the result is
clamped to 0-100 %. `battery_soc_pct` is the charge at the **end** of that hour, rounded to 2 decimals.

Worked example: 15:00, predicted 182.41 kW, solar 169 W/m2, starting at 90 %. The hour is `RENEWABLE_STORAGE`
(over 160 kW). Solar adds 169 / 1000 x 200 = 33.8 kWh and the load takes 182.41 kWh, a net of -148.61 kWh, which is
-7.43 % of 2,000 kWh. The charge at the end of the hour is **82.57 %**.

### What the battery does and does not do

- `battery_low` is true when the charge is **below** 20 % (exactly 20.00 % is not low), judged on the displayed value.
- A low battery raises a warning (`BATTERY_LOW` event, banner) and **never changes `grid_mode`**: the controller rules
  above decide the mode, the battery only reports the consequence.
- `BATTERY_LOW` is raised once each time the charge drops below 20 %, not for every low hour. If it recovers above
  20 % and drops again, a second event is raised. If a forecast starts below 20 %, the event is raised on its first hour.
- A missing solar value counts as 0 (no free energy assumed).
- When a stretch of storage hours is longer than the battery can cover, the charge sits at 0 % while the mode stays
  `RENEWABLE_STORAGE`. That is deliberate: the dashboard flags the shortfall instead of hiding it.

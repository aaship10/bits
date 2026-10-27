# Catalyst Data Store schema

Three tables. Create them in the Catalyst console (**Cloud Scale -> Data Store -> Create Table**) with exactly
these names and columns **before** deploying: the SDK inserts rows but never creates tables or columns.
`backend/storage.py` writes these columns and nothing else, and `backend/tests/test_storage.py` checks this
document against the code, so keep them in step.

Catalyst adds `ROWID`, `CREATORID`, `CREATEDTIME` and `MODIFIEDTIME` to every table; do not create them.
`storage.py` orders by `CREATEDTIME` / `ROWID` to find the newest rows.

## Column types

The Data Store has **no boolean type**. Boolean fields (`overload_alert`, `battery_low`) are Var Char holding
the text `true` or `false`; `storage.py` converts them back to real booleans on read. Timestamps are Var Char too,
because the contract's ISO-8601 strings (`2026-10-25T10:15:00Z`) are not the console's DateTime format.

| Console type | Limit | Used for |
|---|---|---|
| Var Char | 255 characters | ids, timestamps, modes, flags |
| Text | 10,000 characters | log messages (storage.py cuts them at 2,000) |
| Int | 10 digits | counts |
| Double | 17 digits | measurements |

## `forecasts` (one row per forecast; written last, so a row here means the forecast is complete)

| Column | Type | Mandatory | Example | Notes |
|---|---|---|---|---|
| `forecast_id` | Var Char | yes, unique | `f_20261025_101500` | must be unique; `save_forecast` rejects a repeat |
| `generated_at` | Var Char | yes | `2026-10-25T10:15:00Z` | |
| `model_source` | Var Char | yes | `quickml` | `quickml` or `fallback` |
| `row_count` | Int | yes | `24` | |
| `peak_kw` | Double | no | `231.5` | |
| `overload_hours` | Int | no | `5` | |

## `forecast_hours` (one row per forecast hour, in the order they were sent)

| Column | Type | Mandatory | Example | Notes |
|---|---|---|---|---|
| `forecast_id` | Var Char | yes | `f_20261025_101500` | links to `forecasts.forecast_id` |
| `timestamp` | Var Char | yes | `2015-06-16 15:00:00` | `YYYY-MM-DD HH:MM:SS` |
| `ambient_temp_c` | Double | no | `35.66` | |
| `humidity_pct` | Double | no | `56.38` | |
| `solar_irradiance_wm2` | Double | no | `169.0` | |
| `predicted_kw` | Double | yes | `182.41` | already rounded to 2 decimals |
| `grid_mode` | Var Char | yes | `RENEWABLE_STORAGE` | `MAIN_GRID` or `RENEWABLE_STORAGE` |
| `mode_reason` | Var Char | yes | `demand_over_160` | `demand_over_160`, `evening_window`, `both`, `normal` |
| `overload_alert` | Var Char | yes | `false` | `true` / `false` |
| `battery_soc_pct` | Double | no | `86.2` | empty if the battery was not simulated |
| `battery_low` | Var Char | yes | `false` | `true` / `false` |

## `system_logs` (one row per log line)

| Column | Type | Mandatory | Example | Notes |
|---|---|---|---|---|
| `time` | Var Char | yes | `2026-10-25T10:15:00.123456Z` | UTC, microseconds, so rows written in the same second sort correctly |
| `level` | Var Char | yes | `CRITICAL` | `INFO`, `WARN`, `CRITICAL` |
| `event` | Var Char | yes | `OVERLOAD` | `UPLOAD`, `MODE_SWITCH`, `OVERLOAD`, `BATTERY_LOW`, `QUICKML_ERROR` |
| `message` | Text | yes | `2015-06-16 20:00:00: Critical overload: predicted 231.50 kW >= 200 kW` | |
| `forecast_id` | Var Char | no | `f_20261025_101500` | empty for events not tied to a forecast |

## Setup steps

1. Console -> Data Store -> **Create Table**, one for each table above, with the column names and types shown.
   Column names are lower-case with underscores, exactly as written.
2. Leave table permissions at the defaults; AppSail reaches the Data Store with the project's admin scope.
3. Set `STORAGE_BACKEND=catalyst` in the AppSail environment and add `zcatalyst-sdk` to the backend's
   requirements (Python 3.10-3.13).
4. Smoke test from the deployed app: `POST /api/forecast` with the sample CSV, then `GET /api/forecast/latest`
   and `GET /api/logs`. All three must return the forecast and its log lines.

## Limits to keep in mind

- Development environment: 5,000 rows per table and 25,000 per project. A 24-hour forecast is 24 `forecast_hours`
  rows, so about 200 forecasts fit. `?all=true` on the 1,000-row sample adds 1,000 rows per run.
- ZCQL returns at most 300 rows per query; `storage.py` pages through longer forecasts.
- `events`, `summary` and `warnings` are not stored. They are rebuilt from the stored hours when a forecast is read,
  and `warnings` comes back empty.

## Local development

Without Catalyst, the same rows go to SQLite: set `STORAGE_BACKEND=sqlite` (the default; file `backend/local_store.db`,
or `SQLITE_PATH`) or `STORAGE_BACKEND=memory` for a throwaway in-process database.

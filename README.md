# HackSphere 3.0 — Grid Demand Forecast

A web app on **Zoho Catalyst** that forecasts hourly energy demand (kW) for the next 24 hours with a regression model trained and published in **Catalyst QuickML**, applies grid-switching rules, simulates battery state, and shows everything on a live dashboard.

- **Live app:** `TODO: <Slate URL>`
- **API:** `TODO: <AppSail URL>` (`GET /api/health`)
- **Team:** `TODO: names for Members 1-4`

## Architecture

```
                     +---------------------+
   Browser  ───────► |  Slate (React/Vite) |   static dashboard, API_BASE_URL from config.js
                     +----------┬----------+
                                │ HTTPS / JSON (CORS)
                     +----------▼----------+
                     |  AppSail (Flask)    |   validation, controller, battery
                     +--┬-------┬--------┬-+
          predict       │       │        │ raw CSVs
        +---------------▼+  +---▼------+ +▼-----------+
        |  QuickML       |  | Data     | | Stratus    |
        |  endpoint      |  | Store    | | telemetry- |
        |  (regression)  |  | 3 tables | | uploads    |
        +----------------+  +----------+ +------------+
```

| Folder | Owner | Purpose |
|---|---|---|
| `predict.py`, `test_eval.py` | Member 1 | Grader entry point and contract check |
| `ml/` | Member 1 | `features.py`, local training, QuickML notes |
| `backend/` | Members 2 and 3 | Flask API, validation, QuickML client, controller, battery, storage |
| `frontend/` | Member 4 | Slate dashboard |
| `docs/` | Everyone | Controller rules, deployment and submission checklists |

## Run locally

### Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

With `API_BASE_URL` empty, the dashboard runs on a **built-in mock of the API contract** (labelled "Demo data (mock API)" in the status bar), so the UI can be developed without the backend.

To point it at a real backend, edit `frontend/public/config.js`:

```js
window.__APP_CONFIG__ = { API_BASE_URL: "https://<your-appsail-url>" };
```

This file is read at runtime, so it can be changed on a deployed build without rebuilding. `VITE_API_BASE_URL` is accepted as a build-time fallback. Adding `?mock` to the page URL forces the mock.

Load the real sample rows (first 24 of the starter kit) into the "Load sample" button:

```bash
npm run sample -- ../sample_test_input.csv
```

### Backend

`TODO (Member 2): pip install -r backend/requirements.txt; python backend/app.py`

### Model scripts

```bash
python test_eval.py      # must print SUCCESS
python predict.py        # see file header for input/output
```

## Environment variables (names only — never commit values)

| Name | Where | Purpose |
|---|---|---|
| `QUICKML_ENDPOINT_URL` | AppSail, `predict.py` | Published QuickML endpoint |
| `QUICKML_API_KEY` **or** `QUICKML_CLIENT_ID` / `QUICKML_CLIENT_SECRET` / `QUICKML_REFRESH_TOKEN` | AppSail, `predict.py` | QuickML auth (Member 1 confirms which) |
| `STRATUS_BUCKET` | AppSail | Bucket for raw CSV uploads (`telemetry-uploads`) |
| `API_BASE_URL` | Frontend (`public/config.js`) | AppSail base URL |

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/forecast` | JSON `{"rows": [...]}` or multipart `file`; `?window=24` (default) or `?all=true` |
| GET | `/api/forecast/latest` | 404 until the first forecast |
| GET | `/api/logs?limit=50` | Event log |
| GET | `/api/health` | `{"status","quickml"}` |

The full response shapes are in the shared contract. Errors are `{"error","details":[]}` with HTTP 400.

## Controller rules (per forecast hour, on `predicted_kw` rounded to 2 decimals)

- `RENEWABLE_STORAGE` if `predicted_kw > 160` **or** the hour is 18-22 inclusive; otherwise `MAIN_GRID`.
- `overload_alert` if `predicted_kw >= 200`, independent of mode.
- `mode_reason`: `demand_over_160`, `evening_window`, `both` or `normal`.
- Boundaries: 160.00 stays on main grid, 160.01 switches; 199.99 no alert, 200.00 alert; 17:00 and 23:00 outside the window, 18:00 and 22:00 inside.

### Battery assumptions (ours; the brief does not define a battery)

Capacity 2000 kWh, starts at 90% SoC, low threshold 20%, clamped 0-100%. Storage hours discharge `predicted_kw × 1 h`; main-grid hours charge from the grid at up to 150 kW; every hour adds solar charging of `irradiance / 1000 × 200 kW`. `battery_low` raises a warning only and never changes the grid mode. Constants live in `backend/battery.py`.

Detailed rules: [`docs/controller_rules.md`](docs/controller_rules.md) (`TODO: Member 3`).

## Model

`TODO (Member 1): model type, features, training data, validation RMSE, QuickML pipeline name.`

Inputs are only `timestamp`, `ambient_temp_c`, `humidity_pct`, `solar_irradiance_wm2`. There are no demand lags, because the hidden test has no demand column.

## Dashboard

Input (editable hourly table with client-side checks, CSV drag-and-drop, 24-hour generator, sample loader), load-curve chart with 160/200 kW lines, evening window and mode-coloured points, hour slider and play button driving every widget, critical overload banner, battery gauge and SoC curve with low-battery warning, summary tiles, hourly table, system log, model-source and API-health indicators. It refreshes the latest forecast, logs and health every 30 seconds.

Mode is encoded by colour **and** marker shape (circle = main grid, diamond = renewable storage); overload is a red ring plus a ⚠ icon, so nothing relies on colour alone.

## Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and the final [`docs/SUBMISSION_CHECKLIST.md`](docs/SUBMISSION_CHECKLIST.md).

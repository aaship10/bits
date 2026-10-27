# Backend (Flask, Catalyst AppSail)

## Run locally
```
cd backend
pip install -r requirements.txt
python app.py            # http://localhost:5000
python -m pytest -q
```
Point the frontend at it with `API_BASE_URL=http://localhost:5000`.

## Environment variables (names only, never commit values)
| Name | Purpose |
|---|---|
| `QUICKML_ENDPOINT_URL` | Published QuickML endpoint. Unset means the fallback model is used. |
| `QUICKML_API_KEY` | Bearer key, if the endpoint uses one (auth method still to be confirmed by Member 1). |
| `STRATUS_BUCKET` | Bucket for raw CSVs (`telemetry-uploads`). Not wired yet; uploads go to `backend/uploads/`. |
| `X_ZOHO_CATALYST_LISTEN_PORT` / `PORT` | Port to listen on. |

## Module map
- `app.py` endpoints, `validation.py` cleaning, `quickml_client.py` model calls + fallback, `uploads.py` raw CSV archive.
- `controller.py`, `battery.py`, `storage.py` are Member 3's. Until they exist, `_fallbacks.py` supplies in-memory versions of the same functions (`apply_rules`, `detect_events`, `simulate`, `save_forecast`, `get_latest_forecast`, `log_event`, `get_logs`).

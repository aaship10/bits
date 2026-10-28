# Deploying the backend to Catalyst AppSail

Based on the Catalyst docs for [Flask on AppSail](https://docs.catalyst.zoho.com/en/serverless/help/appsail/help-guides/python/flask).
The doc does not show the `app-config.json` keys, so let the CLI generate that file instead of writing it by hand.

## 1. Install dependencies into the app folder
AppSail zips the build directory, so packages must sit next to `app.py`:
```
cd backend
python -m pip install -r requirements.txt -t .
python -m pip install --pre zcatalyst-sdk -t .
```
Do not commit these installed packages (they are large). Add them to `.gitignore` or install in a copy.
Skip `pytest` in the deploy copy if size is a problem; pandas and numpy are the biggest packages.

## 2. Initialise and deploy (from the repo root, logged in with `catalyst login`)
```
catalyst init              # pick the team's Catalyst project; select AppSail
catalyst appsail:add       # stack: Python_3_9, source/build dir: backend, name: hacksphere-api
```
Set the **startup command** to `python3 -u app.py` (console, or in the generated `app-config.json`).
The app listens on `X_ZOHO_CATALYST_LISTEN_PORT` automatically.
```
catalyst deploy
```
The CLI prints the AppSail URL. Give it to Member 4 as `API_BASE_URL`.

## 3. Environment variables (console -> AppSail -> Environment Variables)
Names only; values come from Member 1 / the Catalyst console.

| Name | Meaning |
|---|---|
| `QUICKML_ENDPOINT_URL` | Deployment URL of the published QuickML endpoint |
| `QUICKML_ENDPOINT_KEY` | Sent as `X-QUICKML-ENDPOINT-KEY` |
| `CATALYST_ORG_ID` | Sent as `CATALYST-ORG` |
| `QUICKML_ENVIRONMENT` | `Development` or `Production` (default `Production`) |
| `QUICKML_CLIENT_ID`, `QUICKML_CLIENT_SECRET`, `QUICKML_REFRESH_TOKEN` | Auto-refresh the access token (scope `QuickML.deployment.READ`) |
| `QUICKML_ACCESS_TOKEN` | Alternative: a static token (expires about hourly) |
| `ZOHO_ACCOUNTS_URL` | Only if not on `accounts.zoho.com` (data centre) |
| `STRATUS_BUCKET` | `telemetry-uploads` (create the bucket in the console first) |

## 4. Smoke test the live URL
```
curl <URL>/api/health
curl -X POST "<URL>/api/forecast?window=24" -F "file=@sample_test_input.csv"
curl <URL>/api/forecast/latest
curl "<URL>/api/logs?limit=10"
```
`model_source` should be `quickml`. If it says `fallback`, check `/api/logs` for the `QUICKML_ERROR` message.

## Known gaps to settle with teammates
- QuickML request/response body: Member 1's `QUICKML_NOTES.md` must confirm; edit `_build_body()` / `_parse_response()` in `quickml_client.py` if it differs.
- `storage.py` (Member 3): until it exists, forecasts and logs live in memory and reset when the service restarts.
- Single worker only: the in-memory stand-in is per process.

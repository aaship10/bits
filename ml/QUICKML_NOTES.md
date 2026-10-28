# QuickML notes (Member 1)

## Model status
| Item | Value |
|---|---|
| Local best model | Ridge on standardised features, one-hot hour + cooling terms |
| Validation RMSE (train earliest 80%, validate latest 20%, 2015-05-14 .. 06-16) | **9.41** (RF 13.72, GB 11.76, predict-the-mean 72.81) |
| Heat extrapolation (train T<=30 C, test T>31 C) | **ridge 10.57**, RF 34.15, GB 38.58 |
| QuickML published model RMSE | **TODO** (fill in after training; it must beat 9.41, or at least match it) |
| Published endpoint URL | **TODO** (never commit credentials) |

Why ridge: demand = hourly profile + a roughly linear cooling load above ~24 C (~7 kW per C).
Trees cannot extrapolate beyond the training temperatures and 37% of `sample_test_input.csv` is
above 31 C. If QuickML only offers tree models, check its heat behaviour before choosing it.

## Feature columns (exact order, 38 columns), from `ml/features.py`
`hour, hour_sin, hour_cos, hour_0 .. hour_23, is_evening, cooling_deg, temp_x_humidity,
ambient_temp_c, humidity_pct, solar_irradiance_wm2, cooling_x_evening, cooling_x_humidity,
temp_roll3, temp_roll24, solar_roll3`

- `cooling_deg = max(0, T-22)`, `is_evening` = hour 18..22, rolling means are computed in time order.
- Dropped after ablation: day_of_week, is_weekend, month, day_of_year (no weekday effect; month
  and day_of_year only add extrapolation risk), heating_deg, temp lags.
- Training CSV for QuickML: `ml/quickml_train.csv` = those 38 columns + `target_demand_kw`
  (regenerate with `python ml/train_local.py`).
- If using QuickML's own feature engineering from the raw 4 columns instead, compare its RMSE with 9.41.

## How a published endpoint is called (from the Catalyst docs; confirm in the console)
Source: https://docs.catalyst.zoho.com/en/quickml/help/pipeline-endpoints/

- `POST <Deployment URL shown on the endpoint's details page>`
- Headers: `X-QUICKML-ENDPOINT-KEY: <endpoint key>`, `Authorization: Zoho-oauthtoken <access-token>`,
  `CATALYST-ORG: <org id>`, `Environment: Development|Production`
- OAuth scope: `QuickML.deployment.READ`. Tokens come from the Zoho API Console
  (api-console.zoho.com); access tokens expire (about 1 h, **confirm**), so `predict.py` refreshes
  them from `QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET / QUICKML_REFRESH_TOKEN`
  (POST `{accounts host}/oauth/v2/token`, grant_type=refresh_token).
- SDK docs say request keys must match the model's feature names.

**Not in the docs, read from the endpoint's console page and fill in here:**
- [ ] exact request body (single object vs list of rows, wrapper key such as `data`)
- [ ] exact response body (where the numbers are)
- [ ] row limit per request (`QUICKML_BATCH_SIZE`, default 50)
- [ ] access token lifetime
- [ ] data centre (.com / .in / .eu ...) -> `QUICKML_ACCOUNTS_URL`

`predict.py` currently sends `{"data": [ {feature: value, ...}, ... ]}` (the starter template's
format) and accepts `predictions` / `result` / bare lists in the reply. Only `_build_payload` and
`_parse_response` need editing once the real shapes are known.

### Example request/response
TODO paste the console's sample call here (redact keys and tokens).

## Environment variables (names only)
`QUICKML_ENDPOINT_URL, QUICKML_ENDPOINT_KEY, QUICKML_CATALYST_ORG, QUICKML_ENVIRONMENT,
QUICKML_ACCESS_TOKEN` or `QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET / QUICKML_REFRESH_TOKEN`,
`QUICKML_ACCOUNTS_URL, QUICKML_BATCH_SIZE`

## Question for the organizers
> Graders run `python predict.py` against our published QuickML endpoint. The endpoint needs a
> Zoho OAuth token plus an endpoint key and org id. How should graders supply credentials?
> (a) environment variables they set, (b) a public/unauthenticated endpoint, or (c) credentials
> we embed in the submission? If (c), what is safe to embed? Also: what happens on timeout, and
> is it acceptable that predict.py falls back to a local model if the endpoint is unreachable?

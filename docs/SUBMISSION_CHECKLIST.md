# Final submission checklist

Scoring: 35% RMSE on the hidden test, 35% live public deployment, 20% controller logic, 10% UI.

## Live deployment (35%)
- [ ] Public Slate URL opens in incognito with no login
- [ ] `GET <AppSail>/api/health` returns `status: ok` and `quickml: reachable`
- [ ] Forecast from the UI shows `model_source: quickml`
- [ ] Works on a phone over mobile data
- [ ] QuickML endpoint is **published** and the grader can call it (credentials set in the console)

## Model and grader scripts (35%)
- [ ] `python test_eval.py` prints `SUCCESS` from a fresh clone
- [ ] `predict.py` runs alone (inline feature copy), reads credentials from environment variables
- [ ] RMSE and model details are in the README

## Controller (20%)
- [ ] Boundary tests pass: 160.00 / 160.01, 199.99 / 200.00, 17:00 / 18:00 / 22:00 / 23:00
- [ ] `docs/controller_rules.md` exists and matches the code

## UI (10%)
- [ ] No horizontal page scroll at 375 px wide
- [ ] Loading, empty and error states look right (stop the backend and reload to see the error state)

## Repository hygiene
- [ ] No secrets anywhere: search for `refresh_token`, `client_secret`, `api_key`, `Bearer`, `.env`
- [ ] `.env`, `node_modules/`, `dist/` are not committed or zipped
- [ ] README placeholders (`TODO`) are all filled: live URL, team, model and RMSE, backend run steps
- [ ] `frontend/public/config.js` contains the AppSail URL (a public URL, not a secret)
- [ ] Public GitHub repo **or** `TeamName_Submission.zip` built from a clean checkout
- [ ] Clean-clone test: clone the repo into a new folder and run the README steps

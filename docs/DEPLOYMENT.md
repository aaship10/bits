# Deploying to Zoho Catalyst

One Catalyst project holds everything: Slate (frontend), AppSail (backend), QuickML (model), Data Store, Stratus.

Slate natively supports React, Vite and many other frameworks. Its docs: <https://docs.catalyst.zoho.com/en/slate/help/introduction>. Slate availability may depend on your account; check the console first.

## 1. Project (Member 4 creates, invites the others)

1. Console → create project, e.g. `hacksphere-grid`. Invite Members 1-3 as collaborators.
2. Install the CLI and log in: `npm i -g zcatalyst-cli`, then `catalyst login`.
3. In the repo root: `catalyst init` and pick the existing project. Add the features you need (AppSail, Slate).

## 2. Backend first (Member 2, Member 4 helps)

1. `catalyst deploy` for the AppSail app, then copy its URL.
2. In the console, set the AppSail environment variables (names in README; values stay in the console only).
3. **CORS:** the API must allow the Slate origin (`https://<app>.onslate.com` or similar) and answer `OPTIONS` pre-flights for `POST /api/forecast`. Until the Slate URL is known, allow `*`, then tighten.
4. Verify: `curl https://<appsail-url>/api/health` returns `{"status":"ok", ...}`.

## 3. Frontend on Slate (Member 4)

From the repo root, link and deploy the `frontend` folder:

```bash
catalyst slate:link            # choose frontend/, framework "React + Vite"
                               # accept defaults: npm install, npm run build; build path = dist
catalyst deploy slate -m "dashboard"
catalyst deploy slate --production      # when ready for the production environment
```

Local Slate preview: `catalyst serve --only slate`. The default dev command for React + Vite is `npm run dev -- --port $ZC_SLATE_PORT`.

**Pointing the UI at the backend** (no rebuild needed): edit `frontend/public/config.js`, set `API_BASE_URL` to the AppSail URL, and deploy again. If you prefer a build-time value, add `VITE_API_BASE_URL` under the deployment's Configuration → Environment Variables; Slate's docs show `REACT_APP_*` examples, so confirm that a `VITE_` name is passed to the build in your console before relying on it. `config.js` avoids that question.

The Vite config uses `base: './'`, so assets resolve under any Slate URL.

## 4. End-to-end test of the public URL

- [ ] Open the Slate URL in an **incognito** window. Status bar shows "API online" and does **not** show "Demo data (mock API)".
- [ ] Load sample → Run forecast → chart, banner, tiles, table and logs all update.
- [ ] CSV upload of `sample_test_input.csv` works; a malformed CSV shows a readable error.
- [ ] Browser DevTools → Network: no CORS errors, no calls to `localhost`.
- [ ] `model_source` pill reads **QuickML** (not Fallback) once the endpoint is published.
- [ ] Same checks on a phone (real device on mobile data, not only Wi-Fi).
- [ ] Wait 30 s: the "refreshed" time in the status bar moves.

## 5. API mismatches

Do not patch around the backend in the frontend. Record any difference from the contract here and send it to Member 2.

| Date | Endpoint | Expected | Actual | Status |
|---|---|---|---|---|
| | | | | |

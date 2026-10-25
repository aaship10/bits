import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { API_BASE_URL, REFRESH_MS, USE_MOCK } from './config';
import { fmt, timeOf, relTime } from './utils';
import InputPanel from './components/InputPanel';
import { LoadChart, SocChart } from './components/charts';
import { BatteryGauge, HeroCurve, HourControl, HourlyTable, LogPanel, OverloadBanner, StatusPills, Tiles } from './components/widgets';

const NAV = [
  ['input', 'Input'],
  ['forecast', 'Forecast'],
  ['battery', 'Battery'],
  ['hours', 'Hourly'],
  ['logs', 'Logs'],
];

function Section({ id, n, title, lede, children }) {
  return (
    <section id={id} className="section">
      <div className="section__head">
        <span className="section__n">{n}</span>
        <div>
          <h2>{title}</h2>
          {lede && <p className="lede">{lede}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

export default function App() {
  const [forecast, setForecast] = useState(null);
  const [logs, setLogs] = useState(null);
  const [health, setHealth] = useState(null);
  const [errors, setErrors] = useState({ forecast: null, logs: null, health: null });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);
  const busyRef = useRef(false);
  const idRef = useRef(null);

  const setErr = (k, v) => setErrors((e) => ({ ...e, [k]: v }));

  const adopt = useCallback((f) => {
    setForecast(f);
    // Only reset the cursor when a different forecast arrives, not on every 30 s refresh.
    if (f && f.forecast_id !== idRef.current) {
      idRef.current = f.forecast_id;
      setSelected(0);
      setPlaying(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (busyRef.current) return;
    const [f, l, h] = await Promise.allSettled([api.latest(), api.logs(50), api.health()]);
    if (f.status === 'fulfilled') {
      adopt(f.value);
      setErr('forecast', null);
    } else setErr('forecast', f.reason.message);
    if (l.status === 'fulfilled') {
      setLogs(l.value.logs || []);
      setErr('logs', null);
    } else setErr('logs', l.reason.message);
    if (h.status === 'fulfilled') {
      setHealth(h.value);
      setErr('health', null);
    } else {
      setHealth(null);
      setErr('health', h.reason.message);
    }
    setUpdatedAt(new Date());
    setLoading(false);
  }, [adopt]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const hours = forecast?.hours;

  // Play: step through hours, stop at the end.
  useEffect(() => {
    if (!playing || !hours?.length) return undefined;
    const t = setInterval(() => {
      setSelected((s) => {
        if (s >= hours.length - 1) {
          setPlaying(false);
          return s;
        }
        return s + 1;
      });
    }, 900);
    return () => clearInterval(t);
  }, [playing, hours]);

  const run = async (req) => {
    setBusy(true);
    busyRef.current = true;
    setSubmitError(null);
    try {
      const f = await api.forecast(req);
      adopt(f);
      setErr('forecast', null);
      document.getElementById('forecast')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const l = await api.logs(50).catch(() => null);
      if (l) setLogs(l.logs || []);
    } catch (e) {
      setSubmitError(e);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const jump = (i) => {
    setPlaying(false);
    setSelected(i);
  };
  const cur = hours?.[selected];
  const s = forecast?.summary;

  return (
    <>
      <header className="nav">
        <a className="brand" href="#top" aria-label="HackSphere home">
          HackSphere<span>.</span>
        </a>
        <nav className="nav__links" aria-label="Sections">
          {NAV.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>
        <a className="btn btn--dark btn--sm nav__cta" href="#input">
          Run a forecast
        </a>
      </header>

      <main id="top">
        <section className="hero">
          <p className="eyebrow">HackSphere 3.0 · Grid intelligence</p>
          <h1>
            Energy demand,
            <br />
            thought through.
          </h1>
          <p className="hero__lede">
            A 24-hour demand forecast from a QuickML regression model, turned into grid-switching decisions and battery state, hour by hour.
          </p>
          <div className="hero__cta">
            <a className="btn btn--primary" href="#input">
              Enter telemetry →
            </a>
            <a className="btn btn--ghost" href="#forecast">
              See the forecast
            </a>
          </div>

          <div className="hero__panel">
            <HeroCurve hours={hours} />
            <div className="hero__stats">
              {[
                [s ? fmt(s.peak_kw, 0) : '–', 'kW', 'Peak demand' + (s?.peak_timestamp ? ` at ${timeOf(s.peak_timestamp)}` : '')],
                [s ? s.storage_hours : '–', 'h', 'On renewable storage'],
                [s ? s.overload_hours : '–', 'h', 'Overload hours (≥ 200 kW)'],
                [s ? fmt(s.min_soc_pct, 0) : '–', '%', 'Lowest battery level'],
              ].map(([v, u, l]) => (
                <div key={l} className="stat">
                  <div className="stat__v">
                    {v}
                    <span>{u}</span>
                  </div>
                  <div className="stat__l">{l}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="scroll-cue" aria-hidden="true">
            Scroll <i />
          </div>
        </section>

        <div className="statusbar">
          <StatusPills health={health} healthError={errors.health} forecast={forecast} mock={USE_MOCK} />
          <span className="muted small">
            {forecast ? `Forecast ${forecast.forecast_id} · ${relTime(forecast.generated_at)} · ` : ''}
            {updatedAt ? `refreshed ${updatedAt.toLocaleTimeString()} · every ${REFRESH_MS / 1000}s` : 'loading…'}
            <button className="link" onClick={refresh}>
              Refresh now
            </button>
          </span>
        </div>

        <Section id="input" n="01" title="Feed the model" lede="Type hourly telemetry, generate a 24-hour grid, or drop a CSV. The backend validates everything again and reports warnings below.">
          <InputPanel busy={busy} onSubmit={run} apiError={submitError} onClearError={() => setSubmitError(null)} />
        </Section>

        <Section id="forecast" n="02" title="The next 24 hours" lede="Predicted demand against the 160 kW switching line and the 200 kW overload line. The shaded band is the 18:00-22:00 evening window.">
          {loading && !forecast && <div className="skeleton" style={{ height: 420 }} aria-busy="true" />}
          {errors.forecast && (
            <div className="msg msg--error" role="alert">
              <strong>Could not load the latest forecast.</strong> {errors.forecast}{' '}
              <button className="link" onClick={refresh}>Retry</button>
            </div>
          )}
          {!loading && !forecast && !errors.forecast && (
            <div className="empty-state">
              <p>No forecast yet.</p>
              <a className="btn btn--primary" href="#input">Run your first forecast →</a>
            </div>
          )}
          {forecast && hours?.length > 0 && (
            <>
              {forecast.warnings?.length > 0 && (
                <div className="msg msg--warn" role="status">
                  <strong>Data warnings from the backend</strong>
                  <ul>{forecast.warnings.slice(0, 8).map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              )}
              <OverloadBanner hours={hours} onJump={jump} />
              <div className="split">
                <HourControl hours={hours} selected={selected} onSelect={jump} playing={playing} onTogglePlay={() => (selected >= hours.length - 1 ? (setSelected(0), setPlaying(true)) : setPlaying((p) => !p))} />
                <div className="card chart-card">
                  <div className="legend">
                    <span><i className="dot dot--main" /> Main grid</span>
                    <span><i className="dot dot--storage" /> Renewable storage</span>
                    <span><i className="dot dot--alert" /> Overload (red ring)</span>
                    <span><i className="swatch swatch--shade" /> 18:00-22:00 window</span>
                  </div>
                  <LoadChart hours={hours} selected={selected} onSelect={jump} />
                </div>
              </div>
              <Tiles summary={s} />
              {forecast.events?.length > 0 && (
                <div className="events">
                  <span className="eyebrow">Mode switches</span>
                  {forecast.events.map((e, i) => (
                    <span key={i} className="event">
                      <b>{timeOf(e.timestamp)}</b> {e.message}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </Section>

        {hours?.length > 0 && (
          <>
            <Section id="battery" n="03" title="Battery state" lede="Simulated state of charge for the selected hour, and across the whole window.">
              <div className="split split--battery">
                <div className="card">
                  <div className="eyebrow">At {cur?.timestamp.slice(0, 16)}</div>
                  <BatteryGauge hour={cur} />
                </div>
                <div className="card chart-card">
                  <SocChart hours={hours} selected={selected} onSelect={jump} />
                </div>
              </div>
            </Section>

            <Section id="hours" n="04" title="Hour by hour" lede="Click a row to inspect it everywhere on the page.">
              <div className="card card--flush">
                <HourlyTable hours={hours} selected={selected} onSelect={jump} />
              </div>
            </Section>
          </>
        )}

        <Section id="logs" n={hours?.length ? '05' : '03'} title="System log" lede="Uploads, mode switches, overloads and model errors. Newest first.">
          <LogPanel logs={logs} error={errors.logs} loading={loading} />
        </Section>
      </main>

      <footer className="footer">
        <div className="footer__big">
          Plan the grid
          <br />
          before it plans you.
        </div>
        <div className="footer__cols">
          <div>
            <h3>Product</h3>
            {NAV.map(([id, l]) => <a key={id} href={`#${id}`}>{l}</a>)}
          </div>
          <div>
            <h3>System</h3>
            <span>Slate frontend</span>
            <span>AppSail API</span>
            <span>QuickML model</span>
            <span>Data Store · Stratus</span>
          </div>
          <div>
            <h3>HackSphere 3.0</h3>
            <span>Built on Zoho Catalyst</span>
            <span className="muted-on-dark">{USE_MOCK ? 'Running on demo data' : `API: ${API_BASE_URL}`}</span>
          </div>
        </div>
        <div className="footer__base">© 2026 HackSphere team · Forecasts are model estimates, not guarantees.</div>
      </footer>
    </>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { API_BASE_URL, REFRESH_MS, USE_MOCK } from './config';
import { fmt, timeOf, relTime, prettyEvent, EVENT_LABEL } from './utils';
import Btn from './components/Btn';
import InputPanel from './components/InputPanel';
import { LoadChart, SocChart } from './components/charts';
import { ArrowDown, ArrowRight } from './components/icons';
import { BatteryGauge, HeroCurve, HourControl, HourlyTable, Legend, LogPanel, OverloadBanner, StatusTags, Tiles } from './components/widgets';

const NAV = [
  ['input', 'Input'],
  ['forecast', 'Forecast'],
  ['battery', 'Battery'],
  ['hours', 'Hourly'],
  ['logs', 'Logs'],
];

const STEPS = [
  ['01', 'Forecast', 'A QuickML regression model turns temperature, humidity and sunshine into 24 hourly demand values.', '#input'],
  ['02', 'Switch', 'Above 160 kW, or between 18:00 and 22:00, supply moves to renewable storage. At 200 kW an overload alert fires.', '#forecast'],
  ['03', 'Store', 'A simulated 2,000 kWh battery follows every decision and raises a warning below 20% charge.', '#battery'],
];

// Fade-up on first view. Content stays visible if IntersectionObserver is unavailable.
function useReveal(dep) {
  useEffect(() => {
    const els = document.querySelectorAll('.reveal:not(.is-in)');
    if (!('IntersectionObserver' in window)) {
      els.forEach((e) => e.classList.add('is-in'));
      return undefined;
    }
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add('is-in');
            io.unobserve(en.target);
          }
        }),
      { rootMargin: '0px 0px -8% 0px' }
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [dep]);
}

function Section({ id, n, label, title, lede, tone = 'cream', children }) {
  return (
    <section id={id} className={`section section--${tone}`}>
      <div className="container">
        <header className="headline reveal">
          <div className="headline__label">
            <span>{n}</span>
            <span>{label}</span>
          </div>
          <div>
            <h2 className="title-md">{title}</h2>
            {lede && <p className="headline__lede">{lede}</p>}
          </div>
        </header>
        {children}
      </div>
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
  const [light, setLight] = useState(false);
  const busyRef = useRef(false);
  const idRef = useRef(null);
  const warningsRef = useRef({}); // /api/forecast/latest does not return warnings, so keep them per forecast

  const setErr = (k, v) => setErrors((e) => ({ ...e, [k]: v }));

  const adopt = useCallback((f) => {
    if (f) {
      if (f.warnings?.length) warningsRef.current[f.forecast_id] = f.warnings;
      else if (warningsRef.current[f.forecast_id]) f = { ...f, warnings: warningsRef.current[f.forecast_id] };
    }
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

  // Header turns light once the dark hero has scrolled away.
  useEffect(() => {
    const onScroll = () => setLight(window.scrollY > window.innerHeight * 0.85 - 70);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const hours = forecast?.hours;
  useReveal(`${loading}-${forecast?.forecast_id}`);

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
  const togglePlay = () => {
    if (selected >= hours.length - 1) {
      setSelected(0);
      setPlaying(true);
    } else setPlaying((p) => !p);
  };
  const cur = hours?.[selected];
  const s = forecast?.summary;
  const n = (a, b) => (hours?.length ? a : b);

  return (
    <>
      <header className={`c-header ${light ? 'is-light' : ''}`}>
        <div className="container nav-inner">
          <a className="brand" href="#top" aria-label="HackSphere home">
            HackSphere.
          </a>
          <nav className="nav-links" aria-label="Sections">
            {NAV.map(([id, label]) => (
              <a key={id} href={`#${id}`}>
                {label}
              </a>
            ))}
          </nav>
          <StatusTags health={health} healthError={errors.health} forecast={forecast} mock={USE_MOCK} />
        </div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="container hero-top">
            <h1 className="title-xl">
              Energy demand,
              <br />
              thought through.
            </h1>
            <div className="hero-lede">
              <p>A 24-hour demand forecast from a QuickML regression model, turned into grid-switching decisions and battery state, hour by hour.</p>
              <Btn as="a" href="#input">
                Enter telemetry
              </Btn>
            </div>
          </div>

          <HeroCurve hours={hours} />

          <div className="container hero-bottom">
            <div className="line line--white" />
            <div className="hero-figures">
              {[
                [s ? `${fmt(s.peak_kw, 0)} kW` : '–', 'Peak demand' + (s?.peak_timestamp ? ` at ${timeOf(s.peak_timestamp)}` : '')],
                [s ? `${s.storage_hours} h` : '–', 'Supplied by renewable storage'],
                [s ? `${s.overload_hours} h` : '–', 'At or above the 200 kW overload line'],
                [s ? `${fmt(s.min_soc_pct, 0)} %` : '–', 'Lowest battery charge in the window'],
              ].map(([v, l]) => (
                <div key={l} className="hero-figure">
                  <div className="text-xl">{v}</div>
                  <div className="hero-figure__l">{l}</div>
                </div>
              ))}
            </div>
            <a className="hero-scroll" href="#how">
              Scroll <ArrowDown size={14} />
            </a>
          </div>
        </section>

        <section id="how" className="section section--kaki">
          <div className="container">
            <div className="headline headline--offset reveal">
              <div className="headline__label">
                <span>00</span>
                <span>How it works</span>
              </div>
              <h2 className="title-sm">We predict the next 24 hours of demand, decide where each hour's power comes from, and keep the battery honest.</h2>
            </div>
            <div className="steps">
              {STEPS.map(([num, t, d, href]) => (
                <a key={num} href={href} className="step reveal">
                  <span className="step__n">{num}</span>
                  <span className="step__t">{t}</span>
                  <span className="step__d">{d}</span>
                  <span className="step__go">
                    <ArrowRight />
                  </span>
                </a>
              ))}
            </div>
          </div>
        </section>

        <Section id="input" n="01" label="Input" tone="cream" title="Feed the model" lede="Type hourly telemetry, generate a 24-hour grid or drop a CSV. The backend validates it again and reports any warnings below.">
          <div className="reveal">
            <InputPanel busy={busy} onSubmit={run} apiError={submitError} onClearError={() => setSubmitError(null)} />
          </div>
        </Section>

        <Section id="forecast" n="02" label="Forecast" tone="kaki" title="The next 24 hours" lede="Predicted demand against the 160 kW switching line and the 200 kW overload line. The band marks the 18:00 to 22:00 evening window.">
          <div className="meta-row">
            <span>{forecast ? `${forecast.forecast_id} · generated ${relTime(forecast.generated_at)}` : 'No forecast loaded'}</span>
            <span>
              {updatedAt ? `Refreshed ${updatedAt.toLocaleTimeString()} · every ${REFRESH_MS / 1000} s` : 'Loading…'}
              <button className="link" onClick={refresh}>
                Refresh now
              </button>
            </span>
          </div>
          {loading && !forecast && <div className="skeleton" style={{ height: '28rem' }} aria-busy="true" />}
          {errors.forecast && (
            <div className="msg msg--error" role="alert">
              <div>
                <strong>Could not load the latest forecast.</strong>
                <p>{errors.forecast}</p>
              </div>
              <button className="link" onClick={refresh}>
                Retry
              </button>
            </div>
          )}
          {!loading && !forecast && !errors.forecast && (
            <div className="empty-state">
              <p>No forecast yet.</p>
              <Btn as="a" href="#input">
                Run your first forecast
              </Btn>
            </div>
          )}
          {forecast && hours?.length > 0 && (
            <>
              {forecast.warnings?.length > 0 && (
                <div className="msg msg--warn" role="status">
                  <div>
                    <strong>Data warnings from the backend</strong>
                    <ul>
                      {forecast.warnings.slice(0, 8).map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              <OverloadBanner hours={hours} onJump={jump} />
              <div className="split reveal">
                <HourControl hours={hours} selected={selected} onSelect={jump} playing={playing} onTogglePlay={togglePlay} />
                <div className="panel chart-panel">
                  <Legend />
                  <LoadChart hours={hours} selected={selected} onSelect={jump} />
                </div>
              </div>
              <Tiles summary={s} />
              {forecast.events?.length > 0 && (
                <div className="events">
                  <span className="label">Events</span>
                  {forecast.events.slice(0, 16).map((e, i) => {
                    const at = hours.findIndex((h) => h.timestamp.slice(0, 16) === String(e.timestamp).slice(0, 16));
                    return (
                      <button key={i} className={`event event--${String(e.type).toLowerCase()}`} onClick={() => at >= 0 && jump(at)} title="Jump to this hour">
                        <b>{timeOf(e.timestamp)}</b>
                        <span className="event__type">{EVENT_LABEL[e.type] || e.type}</span>
                        {prettyEvent(e.message)}
                      </button>
                    );
                  })}
                  {forecast.events.length > 16 && <span className="label">+{forecast.events.length - 16} more</span>}
                </div>
              )}
            </>
          )}
        </Section>

        {hours?.length > 0 && (
          <>
            <Section id="battery" n="03" label="Battery" tone="cream" title="Battery state" lede="Simulated state of charge for the selected hour, and across the whole window.">
              <div className="split split--battery reveal">
                <div className="panel">
                  <span className="label">At {cur?.timestamp.slice(0, 16)}</span>
                  <BatteryGauge hour={cur} />
                </div>
                <div className="panel chart-panel">
                  <SocChart hours={hours} selected={selected} onSelect={jump} />
                </div>
              </div>
            </Section>

            <Section id="hours" n="04" label="Hourly" tone="kaki" title="Hour by hour" lede="Select a row to inspect that hour everywhere on the page.">
              <div className="panel panel--flush reveal">
                <HourlyTable hours={hours} selected={selected} onSelect={jump} />
              </div>
            </Section>
          </>
        )}

        <Section id="logs" n={n('05', '03')} label="Logs" tone="cream" title="What the system did" lede="Uploads, mode switches, overloads and model errors, newest first.">
          <div className="reveal">
            <LogPanel logs={logs} error={errors.logs} loading={loading} />
          </div>
        </Section>
      </main>

      <footer className="c-footer">
        <div className="container">
          <div className="footer-top">
            <p className="title-sm">Plan the grid before it plans you.</p>
            <Btn as="a" href="#input">
              Run a forecast
            </Btn>
          </div>
          <div className="line line--white" />
          <div className="footer-nav-grid">
            <div>
              <h3>Product</h3>
              {NAV.map(([id, l]) => (
                <a key={id} href={`#${id}`}>
                  {l}
                </a>
              ))}
            </div>
            <div>
              <h3>System</h3>
              <span>Slate frontend</span>
              <span>AppSail API</span>
              <span>QuickML model</span>
              <span>Data Store and Stratus</span>
            </div>
            <div>
              <h3>Status</h3>
              <span>{health ? 'API online' : errors.health ? 'API offline' : 'Checking API'}</span>
              <span className="footer-api">{USE_MOCK ? 'Running on demo data' : API_BASE_URL}</span>
            </div>
          </div>
          <div className="footer-word" aria-hidden="true">
            HackSphere.
          </div>
          <div className="footer-btm">
            <span>© 2026 HackSphere team</span>
            <span>Built on Zoho Catalyst · HackSphere 3.0</span>
            <span>Forecasts are model estimates, not guarantees.</span>
          </div>
        </div>
      </footer>
    </>
  );
}

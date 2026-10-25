import { useMemo } from 'react';
import { MODE_LABEL, REASON_LABEL, fmt, timeOf, dateOf, relTime, labelOf } from '../utils';

export function ModeBadge({ mode, reason, small }) {
  const storage = mode === 'RENEWABLE_STORAGE';
  return (
    <span className={`badge ${storage ? 'badge--storage' : 'badge--main'} ${small ? 'badge--sm' : ''}`} title={reason ? REASON_LABEL[reason] : undefined}>
      <span className="badge__shape" aria-hidden="true">{storage ? '◆' : '●'}</span>
      {MODE_LABEL[mode]}
    </span>
  );
}

export function AlertIcon({ on }) {
  return on ? (
    <span className="alert-icon" role="img" aria-label="Overload alert" title="Overload alert (≥ 200 kW)">
      ⚠
    </span>
  ) : (
    <span className="muted" aria-label="No alert">–</span>
  );
}

export function OverloadBanner({ hours, onJump }) {
  const bad = hours.map((h, i) => ({ h, i })).filter((x) => x.h.overload_alert);
  if (!bad.length) return null;
  const multi = new Set(hours.map((h) => dateOf(h.timestamp))).size > 1;
  return (
    <div className="banner" role="alert">
      <div className="banner__title">
        <span aria-hidden="true">⚠</span> Critical overload · {bad.length} hour{bad.length > 1 ? 's' : ''} at or above 200 kW
      </div>
      <div className="banner__chips">
        {bad.slice(0, 24).map(({ h, i }) => (
          <button key={i} className="chip" onClick={() => onJump(i)} title="Jump to this hour">
            {labelOf(h.timestamp, multi)} · {fmt(h.predicted_kw, 1)} kW
          </button>
        ))}
        {bad.length > 24 && <span className="chip chip--plain">+{bad.length - 24} more</span>}
      </div>
    </div>
  );
}

export function HourControl({ hours, selected, onSelect, playing, onTogglePlay }) {
  const h = hours[selected];
  if (!h) return null;
  const storage = h.grid_mode === 'RENEWABLE_STORAGE';
  return (
    <div className={`state-card ${storage ? 'state-card--storage' : 'state-card--main'}`}>
      <div className="state-card__top">
        <div>
          <div className="eyebrow">Selected hour</div>
          <div className="state-card__time">{h.timestamp.slice(0, 16)}</div>
        </div>
        <ModeBadge mode={h.grid_mode} />
      </div>
      <div className="state-card__kw">
        {fmt(h.predicted_kw, 2)} <span>kW</span>
        {h.overload_alert && (
          <span className="state-card__alert">
            <AlertIcon on /> Overload
          </span>
        )}
      </div>
      <p className="muted small">{REASON_LABEL[h.mode_reason] || h.mode_reason}</p>
      <div className="stepper">
        <button className="btn btn--ghost btn--sm" onClick={() => onSelect(Math.max(0, selected - 1))} disabled={selected === 0} aria-label="Previous hour">
          ‹
        </button>
        <button className="btn btn--dark btn--sm" onClick={onTogglePlay} aria-pressed={playing}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={() => onSelect(Math.min(hours.length - 1, selected + 1))} disabled={selected === hours.length - 1} aria-label="Next hour">
          ›
        </button>
        <input
          className="slider"
          type="range"
          min={0}
          max={hours.length - 1}
          value={selected}
          onChange={(e) => onSelect(Number(e.target.value))}
          aria-label="Forecast hour"
          aria-valuetext={h.timestamp.slice(0, 16)}
        />
        <span className="muted small stepper__count">
          {selected + 1}/{hours.length}
        </span>
      </div>
    </div>
  );
}

export function Tiles({ summary }) {
  if (!summary) return null;
  const items = [
    ['Peak demand', `${fmt(summary.peak_kw, 1)} kW`, summary.peak_timestamp ? `at ${timeOf(summary.peak_timestamp)}` : ''],
    ['Renewable storage', `${summary.storage_hours} h`, 'hours on storage'],
    ['Main grid', `${summary.main_grid_hours} h`, 'hours on main grid'],
    ['Overload', `${summary.overload_hours} h`, 'hours ≥ 200 kW', summary.overload_hours > 0],
  ];
  return (
    <div className="tiles">
      {items.map(([k, v, sub, bad]) => (
        <div key={k} className={`tile ${bad ? 'tile--bad' : ''}`}>
          <div className="eyebrow">{k}</div>
          <div className="tile__v">{v}</div>
          <div className="muted small">{sub}</div>
        </div>
      ))}
    </div>
  );
}

export function BatteryGauge({ hour }) {
  const pct = Math.max(0, Math.min(100, hour?.battery_soc_pct ?? 0));
  const low = hour?.battery_low;
  // Semicircle arc of radius 80 centred at (100,100).
  const R = 80;
  const len = Math.PI * R;
  const color = low ? '#c62828' : pct < 40 ? '#b8690c' : '#2b5c8a';
  return (
    <div className="gauge">
      <svg viewBox="0 0 200 118" role="img" aria-label={`Battery state of charge ${fmt(pct, 1)} percent${low ? ', low' : ''}`}>
        <path d={`M ${100 - R} 100 A ${R} ${R} 0 0 1 ${100 + R} 100`} fill="none" stroke="rgba(20,19,15,0.09)" strokeWidth="14" strokeLinecap="round" />
        <path
          d={`M ${100 - R} 100 A ${R} ${R} 0 0 1 ${100 + R} 100`}
          fill="none"
          stroke={color}
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={`${(pct / 100) * len} ${len}`}
          style={{ transition: 'stroke-dasharray .35s ease' }}
        />
        {/* 20% low-battery tick */}
        <line
          x1={100 - R * Math.cos(Math.PI * 0.2)}
          y1={100 - R * Math.sin(Math.PI * 0.2)}
          x2={100 - (R + 13) * Math.cos(Math.PI * 0.2)}
          y2={100 - (R + 13) * Math.sin(Math.PI * 0.2)}
          stroke="#c62828"
          strokeWidth="2"
        />
        <text x="100" y="92" textAnchor="middle" className="gauge__num">
          {fmt(pct, 1)}%
        </text>
      </svg>
      {low ? (
        <div className="msg msg--error gauge__msg" role="alert">
          <strong>⚠ Low battery</strong> below 20%. Grid mode is unchanged; plan charging or reduce load.
        </div>
      ) : (
        <p className="muted small gauge__msg">Healthy. Warning appears below 20%.</p>
      )}
    </div>
  );
}

export function HourlyTable({ hours, selected, onSelect }) {
  const multi = useMemo(() => new Set(hours.map((h) => dateOf(h.timestamp))).size > 1, [hours]);
  return (
    <div className="table-scroll">
      <table className="grid-table hourly">
        <thead>
          <tr>
            <th>Time</th>
            <th className="num hide-sm">Temp °C</th>
            <th className="num hide-sm">Humidity %</th>
            <th className="num hide-sm">Irradiance</th>
            <th className="num">Demand kW</th>
            <th>Mode</th>
            <th>Alert</th>
            <th className="num">SoC %</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h, i) => (
            <tr key={h.timestamp + i} className={i === selected ? 'is-sel' : ''} onClick={() => onSelect(i)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onSelect(i)}>
              <td className="nowrap">{labelOf(h.timestamp, multi)}</td>
              <td className="num hide-sm">{fmt(h.ambient_temp_c, 1)}</td>
              <td className="num hide-sm">{fmt(h.humidity_pct, 0)}</td>
              <td className="num hide-sm">{fmt(h.solar_irradiance_wm2, 0)}</td>
              <td className="num strong">{fmt(h.predicted_kw, 2)}</td>
              <td>
                <ModeBadge mode={h.grid_mode} reason={h.mode_reason} small />
              </td>
              <td>
                <AlertIcon on={h.overload_alert} />
              </td>
              <td className={`num ${h.battery_low ? 'bad strong' : ''}`}>
                {fmt(h.battery_soc_pct, 1)}
                {h.battery_low ? ' ⚠' : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LEVEL_ICON = { INFO: 'i', WARN: '!', CRITICAL: '⚠' };

export function LogPanel({ logs, error, loading }) {
  const sorted = useMemo(() => [...(logs || [])].sort((a, b) => new Date(b.time) - new Date(a.time)), [logs]);
  return (
    <div className="card log-card">
      {error && <div className="msg msg--error">Logs unavailable: {error}</div>}
      {loading && !logs && <div className="skeleton" style={{ height: 120 }} />}
      {logs && !sorted.length && <p className="empty">No log entries yet. Run a forecast to generate events.</p>}
      <ul className="logs">
        {sorted.map((l, i) => (
          <li key={i} className={`log log--${String(l.level).toLowerCase()}`}>
            <span className="log__lvl" aria-label={l.level}>
              <span aria-hidden="true">{LEVEL_ICON[l.level] || 'i'}</span> {l.level}
            </span>
            <span className="log__body">
              <span className="log__msg">{l.message}</span>
              <span className="muted small">
                {l.event} · {relTime(l.time)}
                {l.forecast_id ? ` · ${l.forecast_id}` : ''}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StatusPills({ health, healthError, forecast, mock }) {
  const api = health ? 'ok' : healthError ? 'down' : 'wait';
  const q = health?.quickml;
  const src = forecast?.model_source;
  return (
    <div className="pills">
      <span className={`pill pill--${api}`} title={healthError || ''}>
        <i aria-hidden="true" /> API {api === 'ok' ? 'online' : api === 'down' ? 'offline' : 'checking'}
      </span>
      {q && (
        <span className={`pill pill--${q === 'reachable' ? 'ok' : 'warn'}`}>
          <i aria-hidden="true" /> QuickML {q}
        </span>
      )}
      {src && (
        <span className={`pill pill--${src === 'quickml' ? 'ok' : 'warn'}`} title="Source of the predictions currently shown">
          <i aria-hidden="true" /> Model: {src === 'quickml' ? 'QuickML' : 'Fallback'}
        </span>
      )}
      {mock && <span className="pill pill--warn"><i aria-hidden="true" /> Demo data (mock API)</span>}
    </div>
  );
}

// Decorative hero curve drawn from the live forecast.
export function HeroCurve({ hours }) {
  const path = useMemo(() => {
    if (!hours?.length) return null;
    const v = hours.map((h) => h.predicted_kw);
    const lo = Math.min(...v, 120);
    const hi = Math.max(...v, 210);
    const W = 1000;
    const H = 300;
    const pts = v.map((y, i) => [(i / Math.max(1, v.length - 1)) * W, H - ((y - lo) / (hi - lo)) * (H - 60) - 20]);
    const d = pts.reduce((acc, [x, y], i) => {
      if (i === 0) return `M ${x} ${y}`;
      const [px, py] = pts[i - 1];
      const cx = (px + x) / 2;
      return `${acc} C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
    }, '');
    const y200 = H - ((200 - lo) / (hi - lo)) * (H - 60) - 20;
    return { d, area: `${d} L ${W} ${H} L 0 ${H} Z`, y200 };
  }, [hours]);
  return (
    <svg className="hero-curve" viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="hc" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#f3f0ea" stopOpacity=".28" />
          <stop offset="1" stopColor="#f3f0ea" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[60, 120, 180, 240].map((y) => (
        <line key={y} x1="0" x2="1000" y1={y} y2={y} stroke="#f3f0ea" strokeOpacity=".08" />
      ))}
      {path && (
        <>
          <line x1="0" x2="1000" y1={path.y200} y2={path.y200} stroke="#ff8a7a" strokeOpacity=".55" strokeDasharray="6 6" />
          <path d={path.area} fill="url(#hc)" />
          <path d={path.d} fill="none" stroke="#f3f0ea" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
        </>
      )}
    </svg>
  );
}

import { useMemo } from 'react';
import { MODE_LABEL, REASON_LABEL, fmt, timeOf, dateOf, relTime, labelOf } from '../utils';
import { Alert, ArrowRight, MarkMain, MarkStorage, Next, Pause, Play, Prev } from './icons';

export function ModeTag({ mode, reason, onDark }) {
  const storage = mode === 'RENEWABLE_STORAGE';
  return (
    <span className={`mode ${storage ? 'mode--storage' : 'mode--main'} ${onDark ? 'mode--dark' : ''}`} title={reason ? REASON_LABEL[reason] : undefined}>
      {storage ? <MarkStorage /> : <MarkMain />}
      {MODE_LABEL[mode]}
    </span>
  );
}

export function AlertIcon({ on }) {
  return on ? (
    <span className="alert-icon" role="img" aria-label="Overload alert" title="Overload alert (at or above 200 kW)">
      <Alert size={18} />
    </span>
  ) : (
    <span className="faint" aria-label="No alert">
      –
    </span>
  );
}

export function OverloadBanner({ hours, onJump }) {
  const bad = hours.map((h, i) => ({ h, i })).filter((x) => x.h.overload_alert);
  if (!bad.length) return null;
  const multi = new Set(hours.map((h) => dateOf(h.timestamp))).size > 1;
  return (
    <div className="banner" role="alert">
      <div className="banner__title">
        <Alert size={20} />
        <span>
          Critical overload · {bad.length} hour{bad.length > 1 ? 's' : ''} at or above 200 kW
        </span>
      </div>
      <div className="banner__chips">
        {bad.slice(0, 24).map(({ h, i }) => (
          <button key={i} className="chip" onClick={() => onJump(i)} title="Jump to this hour">
            {labelOf(h.timestamp, multi)} <b>{fmt(h.predicted_kw, 1)} kW</b>
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
  return (
    <div className="state">
      <div className="state__top">
        <span className="label">Selected hour</span>
        <span className="state__time">{h.timestamp.slice(0, 16)}</span>
      </div>
      <div className="state__mode">
        <ModeTag mode={h.grid_mode} onDark />
        {h.overload_alert && (
          <span className="mode mode--alert">
            <Alert size={14} /> Overload
          </span>
        )}
      </div>
      <div className="state__kw">
        {fmt(h.predicted_kw, 2)}
        <span>kW</span>
      </div>
      <p className="state__reason">{REASON_LABEL[h.mode_reason] || h.mode_reason}</p>

      <div className="stepper">
        <button className="sq" onClick={() => onSelect(Math.max(0, selected - 1))} disabled={selected === 0} aria-label="Previous hour">
          <Prev />
        </button>
        <button className="sq sq--solid" onClick={onTogglePlay} aria-pressed={playing} aria-label={playing ? 'Pause' : 'Play through the forecast'}>
          {playing ? <Pause /> : <Play />}
        </button>
        <button className="sq" onClick={() => onSelect(Math.min(hours.length - 1, selected + 1))} disabled={selected === hours.length - 1} aria-label="Next hour">
          <Next />
        </button>
        <span className="stepper__count">
          {String(selected + 1).padStart(2, '0')}/{String(hours.length).padStart(2, '0')}
        </span>
      </div>
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
    </div>
  );
}

export function Tiles({ summary }) {
  if (!summary) return null;
  const items = [
    ['Peak demand', fmt(summary.peak_kw, 0), 'kW', summary.peak_timestamp ? `reached at ${timeOf(summary.peak_timestamp)}` : ''],
    ['Renewable storage', summary.storage_hours, 'h', 'hours supplied from storage'],
    ['Main grid', summary.main_grid_hours, 'h', 'hours on the main grid'],
    ['Overload', summary.overload_hours, 'h', 'hours at or above 200 kW', summary.overload_hours > 0],
  ];
  return (
    <div className="figures">
      {items.map(([k, v, u, sub, bad]) => (
        <div key={k} className={`figure ${bad ? 'figure--bad' : ''}`}>
          <div className="label">{k}</div>
          <div className="figure__v">
            {v}
            <span>{u}</span>
          </div>
          <div className="figure__sub">{sub}</div>
        </div>
      ))}
    </div>
  );
}

export function BatteryGauge({ hour }) {
  const pct = Math.max(0, Math.min(100, hour?.battery_soc_pct ?? 0));
  const low = hour?.battery_low;
  const R = 84;
  const len = Math.PI * R;
  const tick = (p, outer) => {
    const a = Math.PI * (p / 100);
    return [110 - (R + outer) * Math.cos(a), 110 - (R + outer) * Math.sin(a)];
  };
  const [x1, y1] = tick(20, -9);
  const [x2, y2] = tick(20, 9);
  const [lx, ly] = tick(20, 24);
  return (
    <div className="gauge">
      <svg viewBox="0 0 220 128" role="img" aria-label={`Battery state of charge ${fmt(pct, 1)} percent${low ? ', low' : ''}`}>
        <path d={`M ${110 - R} 110 A ${R} ${R} 0 0 1 ${110 + R} 110`} fill="none" stroke="rgba(20,20,22,0.12)" strokeWidth="6" />
        <path
          d={`M ${110 - R} 110 A ${R} ${R} 0 0 1 ${110 + R} 110`}
          fill="none"
          stroke={low ? '#b3261e' : '#141416'}
          strokeWidth="6"
          strokeDasharray={`${(pct / 100) * len} ${len}`}
          style={{ transition: 'stroke-dasharray .5s cubic-bezier(.2,.7,.2,1)' }}
        />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#b3261e" strokeWidth="1.5" />
        <text x={lx} y={ly} textAnchor="middle" className="gauge__tick">
          20
        </text>
        <text x="110" y="104" textAnchor="middle" className="gauge__num">
          {fmt(pct, 1)}
          <tspan className="gauge__unit">%</tspan>
        </text>
      </svg>
      {low ? (
        <div className="msg msg--error" role="alert">
          <Alert size={16} />
          <div>
            <strong>Low battery</strong>
            <p>Below 20%. The grid mode is unchanged; plan charging or reduce load.</p>
          </div>
        </div>
      ) : (
        <p className="gauge__ok">Above the 20% low-battery threshold.</p>
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
            <th className="num hide-sm">Irradiance W/m²</th>
            <th className="num">Demand kW</th>
            <th>Mode</th>
            <th>Alert</th>
            <th className="num">Battery %</th>
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
                <ModeTag mode={h.grid_mode} reason={h.mode_reason} />
              </td>
              <td>
                <AlertIcon on={h.overload_alert} />
              </td>
              <td className={`num ${h.battery_low ? 'bad strong' : ''}`}>
                {fmt(h.battery_soc_pct, 1)}
                {h.battery_low && <Alert size={13} style={{ marginLeft: 6, verticalAlign: '-2px' }} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LogPanel({ logs, error, loading }) {
  const sorted = useMemo(() => [...(logs || [])].sort((a, b) => new Date(b.time) - new Date(a.time)), [logs]);
  return (
    <div className="panel panel--flush">
      {error && (
        <div className="msg msg--error" style={{ margin: '1rem' }}>
          <Alert size={16} /> <div>Logs unavailable: {error}</div>
        </div>
      )}
      {loading && !logs && <div className="skeleton" style={{ height: 160 }} />}
      {logs && !sorted.length && <p className="empty">No log entries yet. Run a forecast to generate events.</p>}
      <ul className="logs">
        {sorted.map((l, i) => (
          <li key={i} className="log">
            <span className="log__time">{relTime(l.time)}</span>
            <span className={`lvl lvl--${String(l.level).toLowerCase()}`}>{l.level}</span>
            <span className="log__body">
              <span className="log__msg">{l.message}</span>
              <span className="log__meta">
                {l.event}
                {l.forecast_id ? ` · ${l.forecast_id}` : ''}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StatusTags({ health, healthError, forecast, mock }) {
  const api = health ? 'ok' : healthError ? 'down' : 'wait';
  const q = health?.quickml;
  const src = forecast?.model_source;
  return (
    <div className="tags">
      <span className={`tag tag--${api}`} title={healthError || ''}>
        <i aria-hidden="true" /> API {api === 'ok' ? 'online' : api === 'down' ? 'offline' : '…'}
      </span>
      {q && (
        <span className={`tag tag--opt tag--${q === 'reachable' ? 'ok' : 'warn'}`}>
          <i aria-hidden="true" /> QuickML {q}
        </span>
      )}
      {src && (
        <span className={`tag tag--opt tag--${src === 'quickml' ? 'ok' : 'warn'}`} title="Source of the predictions currently shown">
          <i aria-hidden="true" /> {src === 'quickml' ? 'QuickML model' : 'Fallback model'}
        </span>
      )}
      {mock && (
        <span className="tag tag--warn">
          <i aria-hidden="true" /> Demo data
        </span>
      )}
    </div>
  );
}

export function Legend() {
  return (
    <div className="legend">
      <span>
        <MarkMain size={11} /> Main grid
      </span>
      <span>
        <MarkStorage size={13} style={{ color: '#2f6b4f' }} /> Renewable storage
      </span>
      <span>
        <i className="ring" /> Overload
      </span>
      <span>
        <i className="band" /> 18:00 - 22:00
      </span>
    </div>
  );
}

// Data-driven hero visual: the live forecast drawn as a thin line across the full width.
export function HeroCurve({ hours }) {
  const geo = useMemo(() => {
    if (!hours?.length) return null;
    const v = hours.map((h) => h.predicted_kw);
    const lo = Math.min(...v, 120);
    const hi = Math.max(...v, 210);
    const W = 1000;
    const H = 300;
    const yOf = (y) => H - ((y - lo) / (hi - lo)) * (H - 50) - 20;
    const pts = v.map((y, i) => [(i / Math.max(1, v.length - 1)) * W, yOf(y)]);
    const d = pts.reduce((acc, [x, y], i) => {
      if (i === 0) return `M ${x} ${y}`;
      const [px, py] = pts[i - 1];
      const cx = (px + x) / 2;
      return `${acc} C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
    }, '');
    const eve = hours
      .map((h, i) => ({ i, hr: Number(h.timestamp.slice(11, 13)) }))
      .filter((x) => x.hr >= 18 && x.hr <= 22)
      .map((x) => (x.i / Math.max(1, v.length - 1)) * W);
    return { d, area: `${d} L ${W} ${H} L 0 ${H} Z`, y160: yOf(160), y200: yOf(200), eve: eve.length ? [Math.min(...eve), Math.max(...eve)] : null };
  }, [hours]);
  return (
    <div className="hero-visual" aria-hidden="true">
      <svg viewBox="0 0 1000 300" preserveAspectRatio="none">
        <defs>
          <linearGradient id="hc" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#fffdf1" stopOpacity=".18" />
            <stop offset="1" stopColor="#fffdf1" stopOpacity="0" />
          </linearGradient>
        </defs>
        {geo?.eve && <rect x={geo.eve[0] - 20} width={geo.eve[1] - geo.eve[0] + 40} y="0" height="300" fill="#fffdf1" opacity=".06" />}
        {geo && (
          <>
            <line x1="0" x2="1000" y1={geo.y160} y2={geo.y160} stroke="#fffdf1" strokeOpacity=".25" strokeDasharray="4 6" vectorEffect="non-scaling-stroke" />
            <line x1="0" x2="1000" y1={geo.y200} y2={geo.y200} stroke="#e8685c" strokeOpacity=".6" strokeDasharray="4 6" vectorEffect="non-scaling-stroke" />
            <path d={geo.area} fill="url(#hc)" />
            <path d={geo.d} fill="none" stroke="#fffdf1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          </>
        )}
      </svg>
      {geo && (
        <>
          <span className="hero-visual__tag hero-visual__tag--200" style={{ top: `${(geo.y200 / 300) * 100}%` }}>
            200 kW
          </span>
          <span className="hero-visual__tag" style={{ top: `${(geo.y160 / 300) * 100}%` }}>
            160 kW
          </span>
        </>
      )}
    </div>
  );
}

export { ArrowRight };

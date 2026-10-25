import { useRef, useState } from 'react';
import { parseCsv } from '../csv';
import { validateRows, rowsToPayload } from '../validate';
import { SAMPLE_ROWS, IS_PLACEHOLDER } from '../sample';
import { addHours, fromApiTs, toApiTs } from '../utils';

let uid = 0;
const mk = (r = {}) => ({
  id: ++uid,
  timestamp: r.timestamp ? fromApiTs(r.timestamp) : '',
  ambient_temp_c: r.ambient_temp_c ?? '',
  humidity_pct: r.humidity_pct ?? '',
  solar_irradiance_wm2: r.solar_irradiance_wm2 ?? '',
});

const FIELDS = [
  ['timestamp', 'Timestamp', 'datetime-local'],
  ['ambient_temp_c', 'Temp (°C)', 'number'],
  ['humidity_pct', 'Humidity (%)', 'number'],
  ['solar_irradiance_wm2', 'Irradiance (W/m²)', 'number'],
];

const apiRows = (rows) => rowsToPayload(rows.map((r) => ({ ...r, timestamp: toApiTs(r.timestamp) })));

export default function InputPanel({ busy, onSubmit, apiError, onClearError }) {
  const [tab, setTab] = useState('manual');
  const [rows, setRows] = useState(() => SAMPLE_ROWS.map(mk));
  const [file, setFile] = useState(null);
  const [csvInfo, setCsvInfo] = useState(null); // {rows, errors}
  const [showAll, setShowAll] = useState(false);
  const [checks, setChecks] = useState({ errors: [], warnings: [] });
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);

  const clearAll = () => {
    onClearError?.();
    setChecks({ errors: [], warnings: [] });
  };

  const update = (id, field, value) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
    clearAll();
  };

  const addRow = () => {
    const last = rows[rows.length - 1];
    const next = last?.timestamp ? addHours(last.timestamp, 1) : '';
    setRows((rs) => [...rs, mk({ timestamp: next ? toApiTs(next) : '' })]);
  };

  const generate24 = () => {
    const last = rows[rows.length - 1];
    let start;
    if (last?.timestamp) start = addHours(last.timestamp, 1);
    else {
      const d = new Date();
      start = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:00`;
    }
    const gen = Array.from({ length: 24 }, (_, i) => mk({ timestamp: toApiTs(addHours(start, i)) }));
    // Replace blank placeholder rows, otherwise append.
    const hasData = rows.some((r) => r.ambient_temp_c !== '' || r.humidity_pct !== '' || r.solar_irradiance_wm2 !== '');
    setRows(hasData ? [...rows, ...gen] : gen);
    clearAll();
  };

  const loadSample = () => {
    setTab('manual');
    setFile(null);
    setCsvInfo(null);
    setRows(SAMPLE_ROWS.map(mk));
    clearAll();
  };

  const readFile = async (f) => {
    if (!f) return;
    clearAll();
    if (!/\.csv$/i.test(f.name) && f.type !== 'text/csv') {
      setFile(null);
      setCsvInfo({ rows: [], errors: ['Please choose a .csv file.'] });
      return;
    }
    const parsed = parseCsv(await f.text());
    setFile(f);
    setCsvInfo(parsed);
    if (!parsed.errors.length) setChecks(validateRows(parsed.rows));
  };

  const loadCsvIntoTable = () => {
    setRows(csvInfo.rows.map(mk));
    setFile(null);
    setCsvInfo(null);
    setTab('manual');
    setChecks({ errors: [], warnings: [] });
  };

  const submit = () => {
    if (tab === 'csv') {
      if (!file || !csvInfo || csvInfo.errors.length) return;
      const c = validateRows(csvInfo.rows);
      setChecks(c);
      if (c.errors.length) return;
      onSubmit({ file, all: showAll });
      return;
    }
    const payload = apiRows(rows);
    const c = validateRows(payload);
    setChecks(c);
    if (c.errors.length) return;
    onSubmit({ rows: payload, all: showAll });
  };

  const cellErr = (i, f) => checks.errors.some((e) => e.row === i && e.field === f);

  return (
    <div className="card input-card">
      <div className="tabs" role="tablist" aria-label="Input method">
        {[
          ['manual', 'Manual entry'],
          ['csv', 'CSV upload'],
        ].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`tab ${tab === k ? 'is-on' : ''}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
        <span className="tabs__spacer" />
        <button className="btn btn--ghost btn--sm" onClick={loadSample}>
          Load sample (24 h)
        </button>
      </div>

      {IS_PLACEHOLDER && (
        <p className="note">
          Sample is synthetic until <code>npm run sample</code> loads the real first 24 rows of sample_test_input.csv.
        </p>
      )}

      {tab === 'manual' ? (
        <>
          <div className="toolbar">
            <button className="btn btn--ghost btn--sm" onClick={addRow}>
              + Add row
            </button>
            <button className="btn btn--ghost btn--sm" onClick={generate24}>
              Generate next 24 hours
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => { setRows([]); clearAll(); }} disabled={!rows.length}>
              Clear
            </button>
            <span className="muted small">{rows.length} row{rows.length === 1 ? '' : 's'}</span>
          </div>
          <div className="table-scroll table-scroll--input">
            <table className="grid-table input-table">
              <thead>
                <tr>
                  <th className="num">#</th>
                  {FIELDS.map(([k, l]) => (
                    <th key={k}>{l}</th>
                  ))}
                  <th aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.id}>
                    <td className="num muted">{i + 1}</td>
                    {FIELDS.map(([k, l, type]) => (
                      <td key={k}>
                        <input
                          className={`cell ${cellErr(i, k) ? 'is-bad' : ''}`}
                          type={type}
                          step={type === 'number' ? 'any' : undefined}
                          value={r[k]}
                          aria-label={`${l} row ${i + 1}`}
                          aria-invalid={cellErr(i, k)}
                          onChange={(e) => update(r.id, k, e.target.value)}
                        />
                      </td>
                    ))}
                    <td>
                      <button className="icon-btn" aria-label={`Remove row ${i + 1}`} onClick={() => { setRows((rs) => rs.filter((x) => x.id !== r.id)); clearAll(); }}>
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={6} className="empty">
                      No rows yet. Add a row, generate 24 hours, or load the sample.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div
          className={`drop ${drag ? 'is-drag' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); readFile(e.dataTransfer.files?.[0]); }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        >
          <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => readFile(e.target.files?.[0])} />
          <div className="drop__icon" aria-hidden="true">↑</div>
          <p className="drop__title">{file ? file.name : 'Drop a CSV here, or click to browse'}</p>
          <p className="muted small">
            {csvInfo && !csvInfo.errors.length
              ? `${csvInfo.rows.length} rows read`
              : 'Columns: timestamp, ambient_temp_c, humidity_pct, solar_irradiance_wm2'}
          </p>
          {csvInfo && !csvInfo.errors.length && (
            <button className="btn btn--ghost btn--sm" onClick={(e) => { e.stopPropagation(); loadCsvIntoTable(); }}>
              Edit these rows in the table
            </button>
          )}
        </div>
      )}

      {csvInfo?.errors.length > 0 && tab === 'csv' && <Messages kind="error" title="This file can't be used" items={csvInfo.errors} />}
      {checks.errors.length > 0 && <Messages kind="error" title="Fix these before running" items={checks.errors.map((e) => e.msg)} />}
      {checks.warnings.length > 0 && <Messages kind="warn" title="Heads up" items={checks.warnings} />}
      {apiError && (
        <Messages kind="error" title={`Backend rejected the request: ${apiError.message}`} items={apiError.details?.length ? apiError.details : []} />
      )}

      <div className="submit-row">
        <label className="check">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          <span>Forecast all rows (default: first 24 hours)</span>
        </label>
        <button className="btn btn--primary" onClick={submit} disabled={busy || (tab === 'csv' && (!file || csvInfo?.errors.length > 0))}>
          {busy ? 'Forecasting…' : 'Run forecast →'}
        </button>
      </div>
    </div>
  );
}

function Messages({ kind, title, items }) {
  return (
    <div className={`msg msg--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <strong>{title}</strong>
      {items.length > 0 && (
        <ul>
          {items.slice(0, 12).map((m, i) => (
            <li key={i}>{m}</li>
          ))}
          {items.length > 12 && <li>…and {items.length - 12} more</li>}
        </ul>
      )}
    </div>
  );
}

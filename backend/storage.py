"""Persistence for forecasts and system logs.

Two interchangeable backends behind four functions:

    save_forecast(forecast)                      store a forecast (API-contract shape)
    get_latest_forecast()                        newest forecast, or None
    log_event(level, event, message, forecast_id)
    get_logs(limit)                              newest first

Backend, chosen by the STORAGE_BACKEND environment variable:
    sqlite   (default)  local file, SQLITE_PATH (default backend/local_store.db)
    memory              in-process SQLite, gone on restart (handy for tests)
    catalyst            Catalyst Data Store through the zcatalyst-sdk package

Table and column names are the contract's (see docs/datastore_schema.md). Both backends
store identical rows: booleans are the strings "true"/"false" because the Data Store has
no boolean column type, numbers are Double / Int.

`events`, `summary` and `warnings` have no table; on read they are rebuilt from the stored
hours (warnings come back empty).
"""
from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone

try:  # imported as a package (backend.storage) or from inside backend/
    from .battery import detect_low_events
    from .controller import (LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, detect_events, format_timestamp,
                             round_kw, sort_events, summarize)
except ImportError:
    from battery import detect_low_events
    from controller import (LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, detect_events, format_timestamp,
                            round_kw, sort_events, summarize)

log = logging.getLogger(__name__)

# --- Schema (keep in step with docs/datastore_schema.md; a test compares them) ---------------
VARCHAR, TEXT, INT, DOUBLE = "varchar", "text", "int", "double"

SCHEMA = {
    "forecasts": [
        ("forecast_id", VARCHAR), ("generated_at", VARCHAR), ("model_source", VARCHAR),
        ("row_count", INT), ("peak_kw", DOUBLE), ("overload_hours", INT),
    ],
    "forecast_hours": [
        ("forecast_id", VARCHAR), ("timestamp", VARCHAR), ("ambient_temp_c", DOUBLE),
        ("humidity_pct", DOUBLE), ("solar_irradiance_wm2", DOUBLE), ("predicted_kw", DOUBLE),
        ("grid_mode", VARCHAR), ("mode_reason", VARCHAR), ("overload_alert", VARCHAR),
        ("battery_soc_pct", DOUBLE), ("battery_low", VARCHAR),
    ],
    "system_logs": [
        ("time", VARCHAR), ("level", VARCHAR), ("event", VARCHAR), ("message", TEXT),
        ("forecast_id", VARCHAR),
    ],
}

LEVELS = (LEVEL_INFO, LEVEL_WARN, LEVEL_CRITICAL)
EVENTS = ("UPLOAD", "MODE_SWITCH", "OVERLOAD", "BATTERY_LOW", "QUICKML_ERROR")
_DEFAULT_LEVEL = {"UPLOAD": LEVEL_INFO, "MODE_SWITCH": LEVEL_INFO, "OVERLOAD": LEVEL_CRITICAL,
                  "BATTERY_LOW": LEVEL_WARN, "QUICKML_ERROR": LEVEL_CRITICAL}

DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 500
MAX_MESSAGE_CHARS = 2000   # Text columns hold 10,000; Var Char holds 255
INSERT_CHUNK = 100         # rows per insert_rows call
ZCQL_PAGE = 300            # ZCQL SELECT returns at most 300 rows
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")  # forecast_id goes into a query string

_HOUR_FIELDS = ("timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2",
                "predicted_kw", "grid_mode", "mode_reason", "overload_alert",
                "battery_soc_pct", "battery_low")
_BOOL_FIELDS = ("overload_alert", "battery_low")
_NUM_FIELDS = ("ambient_temp_c", "humidity_pct", "solar_irradiance_wm2", "predicted_kw",
               "battery_soc_pct")


# --- Value conversion ------------------------------------------------------------------------
def _num(value):
    """float, or None for missing / NaN / unparseable (JSON cannot carry NaN)."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _num(value)
    return None if number is None else int(number)


def _bool_text(value) -> str:
    return "true" if _parse_bool(value) else "false"


def _parse_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _check_id(forecast_id) -> str:
    if not isinstance(forecast_id, str) or not _ID_PATTERN.match(forecast_id):
        raise ValueError(f"invalid forecast_id: {forecast_id!r}")
    return forecast_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hour_to_row(forecast_id: str, hour: dict) -> dict:
    row = {"forecast_id": forecast_id, "timestamp": format_timestamp(hour["timestamp"])}
    for key in _NUM_FIELDS:
        row[key] = _num(hour.get(key))
    row["predicted_kw"] = round_kw(hour["predicted_kw"])
    row["grid_mode"] = str(hour["grid_mode"])
    row["mode_reason"] = str(hour["mode_reason"])
    for key in _BOOL_FIELDS:
        row[key] = _bool_text(hour.get(key, False))
    return row


def _row_to_hour(row: dict) -> dict:
    hour = {"timestamp": row["timestamp"]}
    for key in _NUM_FIELDS:
        hour[key] = _num(row.get(key))
    hour["grid_mode"] = row["grid_mode"]
    hour["mode_reason"] = row["mode_reason"]
    for key in _BOOL_FIELDS:
        hour[key] = _parse_bool(row.get(key))
    return {key: hour[key] for key in _HOUR_FIELDS}  # contract key order


# --- SQLite backend (also serves STORAGE_BACKEND=memory) -----------------------------------
_SQL_TYPE = {VARCHAR: "TEXT", TEXT: "TEXT", INT: "INTEGER", DOUBLE: "REAL"}


class SqliteStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            for table, columns in SCHEMA.items():
                cols = ", ".join(f'"{name}" {_SQL_TYPE[kind]}' for name, kind in columns)
                self._db.execute(
                    f'CREATE TABLE IF NOT EXISTS {table} (seq INTEGER PRIMARY KEY AUTOINCREMENT, {cols})')

    def _insert(self, table, rows):
        names = [name for name, _ in SCHEMA[table]]
        sql = (f'INSERT INTO {table} ({", ".join(chr(34) + n + chr(34) for n in names)}) '
               f'VALUES ({", ".join("?" * len(names))})')
        with self._lock, self._db:
            self._db.executemany(sql, [tuple(row.get(n) for n in names) for row in rows])

    def _select(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def forecast_exists(self, forecast_id):
        return bool(self._select("SELECT 1 AS x FROM forecasts WHERE forecast_id = ?", (forecast_id,)))

    def insert_forecast(self, row):
        self._insert("forecasts", [row])

    def insert_hours(self, rows):
        self._insert("forecast_hours", rows)

    def insert_log(self, row):
        self._insert("system_logs", [row])

    def latest_forecast_row(self):
        rows = self._select("SELECT * FROM forecasts ORDER BY seq DESC LIMIT 1")
        return rows[0] if rows else None

    def hours_for(self, forecast_id):
        return self._select("SELECT * FROM forecast_hours WHERE forecast_id = ? ORDER BY seq", (forecast_id,))

    def recent_logs(self, limit):
        return self._select("SELECT * FROM system_logs ORDER BY seq DESC LIMIT ?", (limit,))


# --- Catalyst Data Store backend ----------------------------------------------------------------
class CatalystStore:
    """Zoho Catalyst Data Store via zcatalyst-sdk (pip install zcatalyst-sdk, Python 3.10-3.13).

    Inside a Flask request the SDK is initialised from the request (what AppSail needs); an
    app already put on flask.g.zc_app is reused. Pass app_provider to supply the SDK app yourself.
    """

    def __init__(self, app_provider=None):
        self._app_provider = app_provider
        if app_provider is None:
            try:
                import zcatalyst_sdk  # noqa: F401  (fail at start-up, not on the first request)
            except ImportError as exc:
                raise RuntimeError(
                    "STORAGE_BACKEND=catalyst needs the Catalyst SDK: pip install zcatalyst-sdk") from exc

    def _app(self):
        if self._app_provider is not None:
            return self._app_provider()
        import zcatalyst_sdk
        try:
            from flask import g, has_request_context, request
        except ImportError:
            return zcatalyst_sdk.initialize()
        if not has_request_context():
            return zcatalyst_sdk.initialize()
        app = getattr(g, "zc_app", None)
        if app is None:
            app = g.zc_app = zcatalyst_sdk.initialize(req=request)
        return app

    def _table(self, name):
        return self._app().datastore().table(name)

    def _query(self, table, sql):
        result = self._app().zcql().execute_query(sql)
        if isinstance(result, dict):
            result = [result]
        return [self._unwrap(row, table) for row in (result or [])]

    @staticmethod
    def _unwrap(row, table):
        """ZCQL rows may come as {col: v} or nested under the table name: {table: {col: v}}."""
        if isinstance(row, dict):
            if isinstance(row.get(table), dict):
                return row[table]
            if len(row) == 1:
                (only,) = row.values()
                if isinstance(only, dict):
                    return only
        return row

    def _insert(self, table, rows):
        names = [name for name, _ in SCHEMA[table]]
        clean = [{n: row[n] for n in names if row.get(n) is not None} for row in rows]
        for start in range(0, len(clean), INSERT_CHUNK):
            self._table(table).insert_rows(clean[start:start + INSERT_CHUNK])

    def forecast_exists(self, forecast_id):
        _check_id(forecast_id)
        rows = self._query("forecasts", f"SELECT ROWID FROM forecasts WHERE forecast_id = '{forecast_id}' LIMIT 1")
        return bool(rows)

    def insert_forecast(self, row):
        self._insert("forecasts", [row])

    def insert_hours(self, rows):
        self._insert("forecast_hours", rows)

    def insert_log(self, row):
        self._insert("system_logs", [row])

    def latest_forecast_row(self):
        rows = self._query("forecasts", "SELECT * FROM forecasts ORDER BY CREATEDTIME DESC LIMIT 1")
        return rows[0] if rows else None

    def hours_for(self, forecast_id):
        _check_id(forecast_id)
        result, offset = [], 0
        while True:  # ZCQL returns at most 300 rows per query
            page = self._query(
                "forecast_hours",
                f"SELECT * FROM forecast_hours WHERE forecast_id = '{forecast_id}' "
                f"ORDER BY ROWID LIMIT {offset}, {ZCQL_PAGE}")
            result.extend(page)
            if len(page) < ZCQL_PAGE:
                return result
            offset += ZCQL_PAGE

    def recent_logs(self, limit):
        rows = self._query("system_logs", f"SELECT * FROM system_logs ORDER BY CREATEDTIME DESC LIMIT {int(limit)}")
        return rows


# --- Backend selection -------------------------------------------------------------------------
_store = None
_store_lock = threading.Lock()


def _build_store():
    backend = os.environ.get("STORAGE_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_store.db")
        return SqliteStore(os.environ.get("SQLITE_PATH") or default)
    if backend == "memory":
        return SqliteStore(":memory:")
    if backend == "catalyst":
        return CatalystStore()
    raise ValueError(f"unknown STORAGE_BACKEND {backend!r}; use sqlite, memory or catalyst")


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            _store = _build_store()
        return _store


def reset_store(store=None):
    """Drop the cached backend (tests) or install a ready-made one."""
    global _store
    with _store_lock:
        _store = store


# --- Public API ----------------------------------------------------------------------------------
def save_forecast(forecast: dict, log_events: bool = True) -> str:
    """Persist a forecast in the API-contract shape and return its forecast_id.

    Needs forecast_id, generated_at, model_source and hours (each already through
    controller.apply_rules and battery.simulate). The hours are written first and the
    `forecasts` row last, so get_latest_forecast never sees a half-written forecast.
    With log_events=True it also writes an UPLOAD log plus one log per MODE_SWITCH /
    OVERLOAD / BATTERY_LOW event in forecast["events"].
    """
    if not isinstance(forecast, dict):
        raise ValueError("forecast must be a dict")
    forecast_id = _check_id(forecast.get("forecast_id"))
    hours = forecast.get("hours")
    if not isinstance(hours, list) or not hours:
        raise ValueError("forecast has no hours")
    for key in ("generated_at", "model_source"):
        if not forecast.get(key):
            raise ValueError(f"forecast is missing {key}")

    store = get_store()
    if store.forecast_exists(forecast_id):
        raise ValueError(f"forecast_id {forecast_id!r} already exists; ids must be unique")

    hour_rows = [_hour_to_row(forecast_id, h) for h in hours]
    summary = summarize([_row_to_hour(r) for r in hour_rows])
    store.insert_hours(hour_rows)
    store.insert_forecast({
        "forecast_id": forecast_id,
        "generated_at": str(forecast["generated_at"]),
        "model_source": str(forecast["model_source"]),
        "row_count": len(hour_rows),
        "peak_kw": summary["peak_kw"],
        "overload_hours": summary["overload_hours"],
    })

    if log_events:
        log_event(LEVEL_INFO, "UPLOAD",
                  f"Forecast {forecast_id} generated: {len(hour_rows)} hours, "
                  f"model_source={forecast['model_source']}", forecast_id)
        for event in forecast.get("events") or []:
            etype = event.get("type")
            if etype in EVENTS:
                level = event.get("level") if event.get("level") in LEVELS else _DEFAULT_LEVEL[etype]
                message = event.get("message", "")
                if event.get("timestamp"):  # the log row's own time is "now", so keep the forecast hour
                    message = f"{event['timestamp']}: {message}"
                log_event(level, etype, message, forecast_id)
    return forecast_id


def get_latest_forecast():
    """The newest saved forecast in the API-contract shape, or None when nothing is saved."""
    store = get_store()
    row = store.latest_forecast_row()
    if row is None:
        return None
    forecast_id = row["forecast_id"]
    hours = [_row_to_hour(r) for r in store.hours_for(forecast_id)]
    events = sort_events(detect_events(hours), detect_low_events(hours))
    return {
        "forecast_id": forecast_id,
        "generated_at": row["generated_at"],
        "model_source": row["model_source"],
        "hours": hours,
        "events": events,
        "summary": summarize(hours),
        "warnings": [],  # not stored
    }


def log_event(level: str, event: str, message: str, forecast_id=None):
    """Write one system log row; returns it, or None if the backend failed.

    Raises ValueError for an unknown level or event (a programming error). Backend failures
    are logged and swallowed: losing a log line must not fail a forecast.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown log level {level!r}; use one of {LEVELS}")
    if event not in EVENTS:
        raise ValueError(f"unknown log event {event!r}; use one of {EVENTS}")
    row = {
        "time": _now_iso(),
        "level": level,
        "event": event,
        "message": str(message)[:MAX_MESSAGE_CHARS],
        "forecast_id": forecast_id or "",
    }
    try:
        get_store().insert_log(row)
    except Exception:
        log.exception("could not write system log (%s %s)", level, event)
        return None
    return {**row, "forecast_id": forecast_id or None}


def get_logs(limit: int = DEFAULT_LOG_LIMIT) -> list:
    """Newest-first list of {time, level, event, message, forecast_id}; limit is clamped to 1..500."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LOG_LIMIT
    limit = max(1, min(limit, MAX_LOG_LIMIT))
    rows = get_store().recent_logs(limit)
    logs = [{
        "time": r["time"], "level": r["level"], "event": r["event"],
        "message": r["message"] or "", "forecast_id": r.get("forecast_id") or None,
    } for r in rows]
    logs.sort(key=lambda entry: entry["time"], reverse=True)  # stable: keeps backend order on ties
    return logs

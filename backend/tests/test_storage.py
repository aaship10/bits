import os
import re
import sys
import threading
import types
from datetime import datetime, timedelta

import pytest

import storage
from battery import simulate
from controller import apply_rules, detect_events, sort_events, summarize
from storage import SCHEMA, CatalystStore, SqliteStore

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "datastore_schema.md")


# --- A fake Catalyst SDK that behaves like the real Data Store where it matters ------------------
class FakeTable:
    def __init__(self, cloud, name):
        self.cloud, self.name = cloud, name

    def insert_rows(self, rows):
        assert isinstance(rows, list) and rows
        self.cloud.insert_calls.append((self.name, len(rows)))
        return [self._add(row) for row in rows]

    def insert_row(self, row):
        return self._add(row)

    def _add(self, row):
        known = {name for name, _ in SCHEMA[self.name]}
        unknown = set(row) - known
        assert not unknown, f"column(s) {unknown} do not exist in table {self.name}"
        self.cloud.counter += 1
        stored = {k: str(v) for k, v in row.items()}  # Catalyst hands everything back as text
        stored["ROWID"] = str(10_000 + self.cloud.counter)
        stored["CREATEDTIME"] = f"2026-10-25 10:15:00:{self.cloud.counter:09d}"
        self.cloud.tables[self.name].append(stored)
        return stored


class FakeZcql:
    PATTERN = re.compile(
        r"^SELECT (?P<cols>.+?) FROM (?P<table>\w+)"
        r"(?: WHERE (?P<wcol>\w+) = '(?P<wval>[^']*)')?"
        r"(?: ORDER BY (?P<ocol>\w+)(?P<desc> DESC)?)?"
        r"(?: LIMIT (?:(?P<offset>\d+),\s*)?(?P<count>\d+))?$")

    def __init__(self, cloud):
        self.cloud = cloud

    def execute_query(self, sql):
        m = self.PATTERN.match(sql.strip())
        assert m, f"fake ZCQL cannot parse: {sql}"
        table = m["table"]
        rows = list(self.cloud.tables[table])
        if m["wcol"]:
            rows = [r for r in rows if r.get(m["wcol"]) == m["wval"]]
        if m["ocol"]:
            key = (lambda r: int(r["ROWID"])) if m["ocol"] == "ROWID" else (lambda r: r[m["ocol"]])
            rows.sort(key=key, reverse=bool(m["desc"]))
        offset, count = int(m["offset"] or 0), min(int(m["count"] or 300), 300)  # 300-row cap
        rows = rows[offset:offset + count]
        if m["cols"] != "*":
            rows = [{c.strip(): r[c.strip()] for c in m["cols"].split(",")} for r in rows]
        self.cloud.queries.append(sql)
        return [{table: r} for r in rows] if self.cloud.nested else rows


class FakeCatalyst:
    def __init__(self, nested=False):
        self.tables = {name: [] for name in SCHEMA}
        self.nested, self.counter, self.insert_calls, self.queries = nested, 0, [], []

    def datastore(self):
        return types.SimpleNamespace(table=lambda name: FakeTable(self, name))

    def zcql(self):
        return FakeZcql(self)


# --- Fixtures -------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_store():
    storage.reset_store()
    yield
    storage.reset_store()


@pytest.fixture(params=["memory", "catalyst", "catalyst-nested"])
def store(request):
    if request.param == "memory":
        s = SqliteStore(":memory:")
    else:
        s = CatalystStore(app_provider=lambda cloud=FakeCatalyst(request.param == "catalyst-nested"): cloud)
        s.cloud = s._app()
    storage.reset_store(s)
    return s


def make_forecast(forecast_id="f_20261025_101500", start="2015-06-16 00:00:00", n=24, kw_offset=0.0,
                  initial_soc=30.0, model_source="quickml"):
    first = datetime.fromisoformat(start)
    rows = []
    for i in range(n):
        ts = first + timedelta(hours=i)
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "ambient_temp_c": 30.0 + i * 0.1, "humidity_pct": 50.0 + i * 0.1,
            "solar_irradiance_wm2": max(0.0, 800.0 - abs(ts.hour - 12) * 100),
            "predicted_kw": 120.0 + kw_offset + (60 if ts.hour in (10, 11, 12) else 0)
                            + (50 if 19 <= ts.hour <= 21 else 0) + (i % 7) * 0.013,
        })
    hours, battery_events = simulate(apply_rules(rows), initial_soc_pct=initial_soc)
    return {
        "forecast_id": forecast_id, "generated_at": "2026-10-25T10:15:00Z", "model_source": model_source,
        "hours": hours, "events": sort_events(detect_events(hours), battery_events),
        "summary": summarize(hours), "warnings": [],
    }


# --- Forecast round trip (all backends) ----------------------------------------------------------------
def test_round_trip_matches_the_contract_shape(store):
    forecast = make_forecast()
    assert storage.save_forecast(forecast) == "f_20261025_101500"
    back = storage.get_latest_forecast()
    assert back == forecast
    assert list(back) == ["forecast_id", "generated_at", "model_source", "hours", "events", "summary", "warnings"]
    assert list(back["hours"][0]) == [
        "timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2", "predicted_kw",
        "grid_mode", "mode_reason", "overload_alert", "battery_soc_pct", "battery_low"]


def test_booleans_come_back_as_real_booleans(store):
    forecast = make_forecast(kw_offset=40.0, initial_soc=21.0)
    storage.save_forecast(forecast)
    for hour in storage.get_latest_forecast()["hours"]:
        assert type(hour["overload_alert"]) is bool and type(hour["battery_low"]) is bool
    assert any(h["overload_alert"] for h in forecast["hours"]) and any(h["battery_low"] for h in forecast["hours"])


def test_events_and_summary_are_rebuilt_on_read(store):
    forecast = make_forecast(kw_offset=40.0, initial_soc=21.0)
    assert {e["type"] for e in forecast["events"]} == {"MODE_SWITCH", "OVERLOAD", "BATTERY_LOW"}
    storage.save_forecast(forecast)
    back = storage.get_latest_forecast()
    assert back["events"] == forecast["events"]
    assert back["summary"] == forecast["summary"]
    assert back["warnings"] == []


def test_empty_store_has_no_latest(store):
    assert storage.get_latest_forecast() is None
    assert storage.get_logs() == []


def test_latest_is_the_most_recently_saved(store):
    storage.save_forecast(make_forecast("f_a", kw_offset=0))
    storage.save_forecast(make_forecast("f_b", kw_offset=15, model_source="fallback"))
    back = storage.get_latest_forecast()
    assert back["forecast_id"] == "f_b" and back["model_source"] == "fallback"
    assert len(back["hours"]) == 24  # f_a's hours are not mixed in


def test_long_forecast_round_trips_past_the_300_row_query_cap(store):
    forecast = make_forecast(n=1000)  # the sample_test_input size, ?all=true
    storage.save_forecast(forecast)
    back = storage.get_latest_forecast()
    assert len(back["hours"]) == 1000
    assert back["hours"] == forecast["hours"]  # same order, nothing dropped or repeated


def test_row_order_is_preserved_even_when_not_chronological(store):
    forecast = make_forecast(n=6)
    forecast["hours"] = [forecast["hours"][i] for i in (3, 1, 5, 0, 4, 2)]
    storage.save_forecast(forecast)
    assert [h["timestamp"] for h in storage.get_latest_forecast()["hours"]] == \
        [h["timestamp"] for h in forecast["hours"]]


def test_duplicate_forecast_id_is_rejected_and_changes_nothing(store):
    storage.save_forecast(make_forecast("f_dup"))
    logs_before = len(storage.get_logs(500))
    with pytest.raises(ValueError, match="already exists"):
        storage.save_forecast(make_forecast("f_dup", kw_offset=30))
    assert len(storage.get_latest_forecast()["hours"]) == 24
    assert len(storage.get_logs(500)) == logs_before


@pytest.mark.parametrize("mutate, message", [
    (lambda f: f.pop("forecast_id"), "forecast_id"),
    (lambda f: f.update(forecast_id="x' OR forecast_id <> '"), "forecast_id"),
    (lambda f: f.update(forecast_id=""), "forecast_id"),
    (lambda f: f.update(forecast_id=None), "forecast_id"),
    (lambda f: f.update(hours=[]), "no hours"),
    (lambda f: f.pop("hours"), "no hours"),
    (lambda f: f.pop("generated_at"), "generated_at"),
    (lambda f: f.pop("model_source"), "model_source"),
])
def test_invalid_forecasts_are_rejected(store, mutate, message):
    forecast = make_forecast()
    mutate(forecast)
    with pytest.raises(ValueError, match=message):
        storage.save_forecast(forecast)
    assert storage.get_latest_forecast() is None


def test_not_a_dict_is_rejected(store):
    with pytest.raises(ValueError):
        storage.save_forecast([1, 2, 3])


def test_hour_with_missing_optional_values_round_trips_as_none(store):
    forecast = make_forecast(n=3)
    forecast["hours"][1]["humidity_pct"] = None
    forecast["hours"][2]["solar_irradiance_wm2"] = float("nan")
    storage.save_forecast(forecast)
    hours = storage.get_latest_forecast()["hours"]
    assert hours[1]["humidity_pct"] is None
    assert hours[2]["solar_irradiance_wm2"] is None
    assert hours[0]["humidity_pct"] == forecast["hours"][0]["humidity_pct"]


def test_forecast_without_battery_fields_still_saves(store):
    hours = apply_rules([{"timestamp": "2015-06-16 10:00:00", "predicted_kw": 100.0},
                         {"timestamp": "2015-06-16 11:00:00", "predicted_kw": 170.0}])
    storage.save_forecast({"forecast_id": "f_nobat", "generated_at": "2026-10-25T10:15:00Z",
                           "model_source": "fallback", "hours": hours})
    back = storage.get_latest_forecast()
    assert back["summary"]["min_soc_pct"] is None
    assert back["hours"][0]["battery_soc_pct"] is None
    assert [e["type"] for e in back["events"]] == ["MODE_SWITCH"]


def test_failed_forecast_row_leaves_no_visible_forecast(store, monkeypatch):
    # hours are written first and the forecasts row last: a crash in between must not surface a partial forecast
    def boom(row):
        raise RuntimeError("datastore down")
    monkeypatch.setattr(store, "insert_forecast", boom)
    with pytest.raises(RuntimeError):
        storage.save_forecast(make_forecast())
    assert storage.get_latest_forecast() is None


# --- Logs (all backends) -------------------------------------------------------------------------------
def test_save_forecast_writes_upload_and_event_logs(store):
    forecast = make_forecast(kw_offset=40.0, initial_soc=21.0)
    storage.save_forecast(forecast)
    logs = storage.get_logs(500)
    assert len(logs) == 1 + len(forecast["events"])
    assert {entry["forecast_id"] for entry in logs} == {"f_20261025_101500"}
    by_event = {}
    for entry in logs:
        by_event.setdefault(entry["event"], []).append(entry)
    assert len(by_event["UPLOAD"]) == 1 and by_event["UPLOAD"][0]["level"] == "INFO"
    assert "24 hours" in by_event["UPLOAD"][0]["message"] and "quickml" in by_event["UPLOAD"][0]["message"]
    assert {e["level"] for e in by_event["OVERLOAD"]} == {"CRITICAL"}
    assert {e["level"] for e in by_event["BATTERY_LOW"]} == {"WARN"}
    assert {e["level"] for e in by_event["MODE_SWITCH"]} == {"INFO"}
    switch = forecast["events"][0]
    assert any(e["message"] == f"{switch['timestamp']}: {switch['message']}" for e in by_event["MODE_SWITCH"])


def test_save_forecast_can_skip_logging(store):
    storage.save_forecast(make_forecast(), log_events=False)
    assert storage.get_logs() == []


def test_logs_are_newest_first_and_every_field_is_present(store):
    for i in range(5):
        storage.log_event("INFO", "UPLOAD", f"upload {i}", f"f_{i}")
    logs = storage.get_logs()
    assert [entry["message"] for entry in logs] == [f"upload {i}" for i in (4, 3, 2, 1, 0)]
    assert set(logs[0]) == {"time", "level", "event", "message", "forecast_id"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", logs[0]["time"])
    assert [entry["time"] for entry in logs] == sorted((e["time"] for e in logs), reverse=True)


def test_log_limit_is_honoured_and_clamped(store):
    for i in range(60):
        storage.log_event("INFO", "UPLOAD", f"m{i}")
    assert len(storage.get_logs()) == 50              # default
    assert len(storage.get_logs(10)) == 10
    assert storage.get_logs(10)[0]["message"] == "m59"
    assert len(storage.get_logs(0)) == 1              # clamped up to 1
    assert len(storage.get_logs(-5)) == 1
    assert len(storage.get_logs(100000)) == 60        # clamped to 500, only 60 exist
    assert len(storage.get_logs("7")) == 7
    assert len(storage.get_logs("abc")) == 50         # unparseable -> default
    assert len(storage.get_logs(None)) == 50


def test_log_without_forecast_id_reads_back_as_none(store):
    storage.log_event("CRITICAL", "QUICKML_ERROR", "QuickML returned 503")
    (entry,) = storage.get_logs()
    assert entry["forecast_id"] is None and entry["event"] == "QUICKML_ERROR" and entry["level"] == "CRITICAL"


def test_log_event_returns_the_row_it_wrote(store):
    written = storage.log_event("WARN", "BATTERY_LOW", "low", "f_1")
    assert written["level"] == "WARN" and written["forecast_id"] == "f_1"
    assert storage.get_logs()[0] == written


def test_long_messages_are_truncated(store):
    storage.log_event("INFO", "UPLOAD", "x" * 50_000)
    assert len(storage.get_logs()[0]["message"]) == storage.MAX_MESSAGE_CHARS


@pytest.mark.parametrize("level, event", [
    ("DEBUG", "UPLOAD"), ("info", "UPLOAD"), ("", "UPLOAD"), (None, "UPLOAD"),
    ("INFO", "NOPE"), ("INFO", "upload"), ("INFO", None),
])
def test_log_event_rejects_unknown_level_or_event(store, level, event):
    with pytest.raises(ValueError):
        storage.log_event(level, event, "x")
    assert storage.get_logs() == []


def test_log_event_swallows_backend_failures(store, monkeypatch, caplog):
    def boom(row):
        raise RuntimeError("datastore down")
    monkeypatch.setattr(store, "insert_log", boom)
    with caplog.at_level("ERROR"):
        assert storage.log_event("INFO", "UPLOAD", "x") is None
    assert "could not write system log" in caplog.text


def test_every_contract_event_type_and_level_is_accepted(store):
    for event in ("UPLOAD", "MODE_SWITCH", "OVERLOAD", "BATTERY_LOW", "QUICKML_ERROR"):
        for level in ("INFO", "WARN", "CRITICAL"):
            assert storage.log_event(level, event, f"{level} {event}") is not None
    assert len(storage.get_logs(500)) == 15


def test_concurrent_logging_loses_nothing():
    storage.reset_store(SqliteStore(":memory:"))

    def worker(n):
        for i in range(25):
            storage.log_event("INFO", "UPLOAD", f"{n}-{i}")
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(storage.get_logs(500)) == 200


# --- Catalyst specifics ----------------------------------------------------------------------------------
@pytest.fixture
def cloud():
    fake = FakeCatalyst()
    storage.reset_store(CatalystStore(app_provider=lambda: fake))
    return fake


def test_catalyst_writes_exactly_the_schema_columns_to_the_three_tables(cloud):
    storage.save_forecast(make_forecast(kw_offset=40.0, initial_soc=21.0))
    assert {n for n, rows in cloud.tables.items() if rows} == set(SCHEMA)  # FakeTable rejects unknown columns
    for table, columns in SCHEMA.items():
        written = set().union(*(set(r) for r in cloud.tables[table])) - {"ROWID", "CREATEDTIME"}
        assert written <= {name for name, _ in columns}


def test_catalyst_stores_booleans_as_text_and_numbers_as_numbers(cloud):
    storage.save_forecast(make_forecast(kw_offset=40.0))
    flags = {r["overload_alert"] for r in cloud.tables["forecast_hours"]}
    assert flags == {"true", "false"}
    assert {r["battery_low"] for r in cloud.tables["forecast_hours"]} <= {"true", "false"}
    assert cloud.tables["forecasts"][0]["row_count"] == "24"


def test_catalyst_forecast_row_is_written_after_its_hours(cloud):
    storage.save_forecast(make_forecast(), log_events=False)
    assert [name for name, _ in cloud.insert_calls] == ["forecast_hours", "forecasts"]


def test_catalyst_bulk_inserts_are_chunked(cloud):
    storage.save_forecast(make_forecast(n=1000), log_events=False)
    hour_calls = [size for name, size in cloud.insert_calls if name == "forecast_hours"]
    assert hour_calls == [100] * 10


def test_catalyst_reads_use_paging_and_the_forecast_id_filter(cloud):
    storage.save_forecast(make_forecast("f_one", n=700), log_events=False)
    storage.save_forecast(make_forecast("f_two", n=10, start="2015-07-01 00:00:00"), log_events=False)
    cloud.queries.clear()
    assert len(storage.get_latest_forecast()["hours"]) == 10
    assert any("ORDER BY CREATEDTIME DESC LIMIT 1" in q for q in cloud.queries)
    assert all("'f_two'" in q for q in cloud.queries if "forecast_hours" in q)
    cloud.queries.clear()
    storage.reset_store(storage.get_store())
    storage.save_forecast(make_forecast("f_three", n=700, start="2016-01-01 00:00:00"), log_events=False)
    cloud.queries.clear()
    storage.get_latest_forecast()
    offsets = [q for q in cloud.queries if "LIMIT" in q and "forecast_hours" in q]
    assert len(offsets) == 3 and "LIMIT 600, 300" in offsets[-1]


def test_catalyst_recent_logs_query(cloud):
    storage.log_event("INFO", "UPLOAD", "x")
    cloud.queries.clear()
    storage.get_logs(7)
    assert cloud.queries == ["SELECT * FROM system_logs ORDER BY CREATEDTIME DESC LIMIT 7"]


def test_catalyst_reads_values_that_arrive_as_text(cloud):
    storage.save_forecast(make_forecast(n=3), log_events=False)
    raw = cloud.tables["forecast_hours"][0]
    assert isinstance(raw["predicted_kw"], str)
    hour = storage.get_latest_forecast()["hours"][0]
    assert isinstance(hour["predicted_kw"], float) and isinstance(hour["battery_low"], bool)


def test_catalyst_unwrap_handles_both_result_shapes():
    flat = {"forecast_id": "f_1"}
    assert CatalystStore._unwrap(flat, "forecasts") == flat
    assert CatalystStore._unwrap({"forecasts": flat}, "forecasts") == flat
    assert CatalystStore._unwrap({"Forecasts": flat}, "forecasts") == flat  # table name in another case
    assert CatalystStore._unwrap({"forecast_id": "f_1", "row_count": "3"}, "forecasts") == \
        {"forecast_id": "f_1", "row_count": "3"}


def test_catalyst_query_accepts_a_single_row_dict_result():
    class OneRow:
        def zcql(self):
            return types.SimpleNamespace(execute_query=lambda sql: {"forecasts": {"forecast_id": "f_1"}})
    s = CatalystStore(app_provider=lambda: OneRow())
    assert s._query("forecasts", "SELECT * FROM forecasts") == [{"forecast_id": "f_1"}]


def test_catalyst_forecast_id_is_validated_before_it_reaches_a_query(cloud):
    s = storage.get_store()
    for bad in ("x' OR '1'='1", "a b", "", "f;DROP", None):
        with pytest.raises(ValueError):
            s.forecast_exists(bad)
        with pytest.raises(ValueError):
            s.hours_for(bad)
    assert cloud.queries == []


def test_catalyst_sdk_is_initialised_from_the_flask_request(monkeypatch):
    flask = pytest.importorskip("flask")
    calls = []
    fake_sdk = types.ModuleType("zcatalyst_sdk")
    fake_sdk.initialize = lambda req=None: calls.append(req) or FakeCatalyst()
    monkeypatch.setitem(sys.modules, "zcatalyst_sdk", fake_sdk)
    store = CatalystStore()
    app = flask.Flask(__name__)
    with app.test_request_context("/api/forecast"):
        first, second = store._app(), store._app()
        assert first is second and len(calls) == 1 and calls[0].path == "/api/forecast"
    with app.test_request_context("/other"):
        flask.g.zc_app = sentinel = FakeCatalyst()  # an app that M2 already put on g is reused
        assert store._app() is sentinel and len(calls) == 1
    store._app()  # no request: plain initialize()
    assert len(calls) == 2 and calls[1] is None


# --- Backend selection ---------------------------------------------------------------------------------------
def test_default_backend_is_sqlite_and_data_survives_a_restart(monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    storage.save_forecast(make_forecast())
    storage.reset_store()  # "restart": a fresh store on the same file
    assert storage.get_latest_forecast()["forecast_id"] == "f_20261025_101500"
    assert len(storage.get_logs()) > 0
    assert (tmp_path / "t.db").exists()


def test_memory_backend_does_not_touch_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "never.db"))
    storage.save_forecast(make_forecast())
    assert not (tmp_path / "never.db").exists()
    storage.reset_store()
    assert storage.get_latest_forecast() is None


def test_backend_name_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", " MEMORY ")
    assert isinstance(storage.get_store(), SqliteStore)


def test_unknown_backend_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        storage.get_store()


def test_catalyst_backend_without_sdk_explains_how_to_fix_it(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "catalyst")
    monkeypatch.setitem(sys.modules, "zcatalyst_sdk", None)  # makes `import zcatalyst_sdk` fail
    with pytest.raises(RuntimeError, match="pip install zcatalyst-sdk"):
        storage.get_store()


def test_store_is_created_once(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    assert storage.get_store() is storage.get_store()


# --- docs/datastore_schema.md must describe exactly what the code writes -----------------------------------------
def test_schema_doc_matches_the_code():
    with open(DOC, encoding="utf-8") as handle:
        text = handle.read()
    type_names = {"Var Char": "varchar", "Text": "text", "Int": "int", "Double": "double"}
    for table, columns in SCHEMA.items():
        section = re.search(rf"^## `{table}`.*?(?=^## |\Z)", text, re.S | re.M)
        assert section, f"{table} missing from docs/datastore_schema.md"
        documented = re.findall(r"^\| `(\w+)` \| ([A-Za-z ]+?) \|", section.group(0), re.M)
        assert [(name, type_names[kind]) for name, kind in documented] == columns

"""The collector against a fake Home Assistant: history import, live polling, restarts, sensors and messages."""
import asyncio
import json
import random

import httpx
import pytest

import db
import demo_data
from collector import Collector
from config import Machine, Settings, load_settings, parse_machines, slug
from fake_ha import FakeHA
from hass import HomeAssistant

T = 1_900_000_000  # far from the demo data


def make(name, readings, **kw):
    machine = Machine(name=name, type=kw.pop("type", "washer"), power_entity=f"sensor.{slug(name)}_power",
                      **{k: v for k, v in kw.items() if k != "states"})
    ha = FakeHA({machine.power_entity: readings}, kw.get("states"))
    settings = Settings(machines=[machine], import_days=3, notify_services=["mobile_app_phone"])
    return Collector(settings, ha), machine, ha


def stored(machine):
    return db.query("SELECT * FROM cycles WHERE machine = ? ORDER BY started_at", [machine.id])


def run(coro):
    return asyncio.run(coro)


def test_first_start_imports_history_without_announcing():
    rnd = random.Random(5)
    readings = (demo_data.wash(T - 2 * 86400, demo_data.WASH_PROGRAMS["40°"], rnd)
                + demo_data.wash(T - 86400 + 3600, demo_data.WASH_PROGRAMS["60°"], rnd))
    c, m, ha = make("Import vask", sorted(readings))
    assert run(c.poll(T)) == 2
    assert [r["source"] for r in stored(m)] == ["history", "history"]
    assert ha.events == [] and ha.services == []  # old washes are not news
    assert run(c.poll(T + 60)) == 0  # nothing is stored twice


def test_live_cycle_is_announced_once():
    readings = demo_data.wash(T, demo_data.WASH_PROGRAMS["40° kort"], random.Random(6))
    c, m, ha = make("Live vask", readings)
    db.set_meta(f"resume:{m.id}", str(T - 120))
    for now in range(int(T), int(readings[-1][0]) + 1200, 30):  # poll every 30 s through the wash
        run(c.poll(now))
    assert len(stored(m)) == 1
    assert stored(m)[0]["source"] == "live"
    assert [e[0] for e in ha.events] == ["laundry_stats_cycle_finished"]
    assert ha.services[0][0] == "notify.mobile_app_phone"
    assert "Live vask er færdig" in ha.services[0][1]["message"]


def test_restart_mid_cycle_gives_one_whole_cycle():
    readings = demo_data.dry(T, 110, random.Random(7))
    c, m, _ = make("Restart tumbler", readings, type="dryer", start_watt=100, start_seconds=60, stop_watt=35,
                   stop_minutes=2)
    db.set_meta(f"resume:{m.id}", str(T - 120))
    run(c.poll(T + 40 * 60))
    assert c.live[m.id]["running"] and c.live[m.id]["minutes"] == 40
    c2 = Collector(c.settings, c.hass)  # the add-on restarts
    run(c2.poll(T + 4 * 3600))
    rows = stored(m)
    assert len(rows) == 1 and rows[0]["minutes"] == pytest.approx(110, abs=0.2)
    assert not c2.live[m.id]["running"]


def test_running_cycle_gets_an_expected_finish():
    rnd = random.Random(8)
    readings = []
    for day in range(3):
        readings += demo_data.wash(T - (3 - day) * 86400, demo_data.WASH_PROGRAMS["60°"], rnd)
    readings += demo_data.wash(T, demo_data.WASH_PROGRAMS["60°"], rnd)
    c, m, ha = make("Gæt vask", sorted(readings))
    c.settings.import_days = 4
    run(c.poll(T + 30 * 60))
    live = c.live[m.id]
    assert live["running"]
    assert abs(live["expected_minutes"] - 93) <= 3
    status, attrs = ha.set_states[f"sensor.laundry_stats_{m.id}_status"]
    assert status == "running" and attrs["expected_minutes"] == live["expected_minutes"]
    assert ha.set_states[f"sensor.laundry_stats_{m.id}_expected_finish"][0] != "unknown"


def test_skip_entity_keeps_descaling_out():
    readings = demo_data.wash(T, demo_data.WASH_PROGRAMS["Bomuld 90°"], random.Random(9))
    c, m, ha = make("Afkalk vask", readings, skip_entity="timer.afkalkning",
                    states={"timer.afkalkning": "active"})
    db.set_meta(f"resume:{m.id}", str(T - 120))
    run(c.poll(readings[-1][0] + 600))
    assert stored(m)[0]["excluded"] == 1
    assert ha.services == []


def test_home_assistant_history_is_parsed():
    """The real client, against answers shaped like Home Assistant's minimal_response history."""
    def handler(request):
        assert request.url.path.startswith("/api/history/period/")
        assert request.url.params["filter_entity_id"] == "sensor.p"
        return httpx.Response(200, json=[[
            {"entity_id": "sensor.p", "state": "3.2", "last_changed": "2030-01-01T10:00:00+00:00", "attributes": {}},
            {"state": "unavailable", "last_changed": "2030-01-01T10:01:00Z"},
            {"state": "1450.5", "last_changed": "2030-01-01T10:02:00.123456+00:00"},
        ]])

    async def go():
        ha = HomeAssistant("http://ha/api", "token", transport=httpx.MockTransport(handler))
        try:
            return await ha.history("sensor.p", 1893492000 - 60, 1893495600)
        finally:
            await ha.close()

    rows = run(go())
    assert [w for _, w in rows] == [3.2, None, 1450.5]
    assert rows[0][0] == 1893492000


def test_machines_from_options(tmp_path, monkeypatch):
    import config
    (tmp_path / "options.json").write_text(json.dumps({"machines": [
        {"name": "Tørretumbler", "type": "dryer", "power_entity": " sensor.t ", "start_watt": 100},
        {"name": "Tørretumbler", "type": "dryer", "power_entity": "sensor.t2"},
        {"name": ""},
    ], "notify_services": [""], "ha_sensors": False}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    s = load_settings()
    assert [m.id for m in s.machines] == ["toerretumbler", "toerretumbler_2"]
    assert s.machines[0].power_entity == "sensor.t"
    assert s.notify_services == [] and s.ha_sensors is False


def test_unknown_type_falls_back_to_washer():
    assert parse_machines([{"name": "X", "type": "oven"}])[0].type == "washer"

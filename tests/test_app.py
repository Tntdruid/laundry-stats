"""The web app on the demo data: every endpoint answers, for every period and machine."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


ENDPOINTS = ["meta", "live", "latest", "summary", "timeline?bucket=day", "timeline?bucket=week",
             "timeline?bucket=month", "heatmap", "durations", "insights", "cycles", "export.csv"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_endpoint_answers(client, path):
    r = client.get(f"/api/{path}")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("days", [0, 7, 30, 365])
def test_every_range_works_for_every_machine(client, days):
    start = 0 if not days else int(datetime.now().timestamp()) - days * 86400
    for machine in ("", "vaskemaskine", "toerretumbler", "findes_ikke"):
        for path in ("summary", "insights", "timeline", "durations", "heatmap", "cycles"):
            assert client.get(f"/api/{path}?start={start}&machine={machine}").status_code == 200


def test_page_and_assets(client):
    assert "Vaskestatistik" in client.get("/").text
    for f in ("app.js", "style.css"):
        assert client.get(f"/static/{f}").status_code == 200


def test_demo_data_was_found(client):
    s = client.get("/api/summary").json()
    assert s["washes"] > 50 and s["dries"] > 30
    assert 0.5 < s["dried_share"] < 0.9
    assert s["excluded"] == 1  # the descaling program
    assert {m["id"] for m in s["machines"]} >= {"vaskemaskine", "toerretumbler"}


def test_previous_period_only_for_a_limited_range(client):
    assert client.get("/api/summary").json()["previous"] is None
    start = int(datetime.now().timestamp()) - 30 * 86400
    assert client.get(f"/api/summary?start={start}").json()["previous"]["n"] >= 0


def test_cycle_detail(client):
    cid = db.query("SELECT id FROM cycles WHERE type = 'dryer' ORDER BY started_at DESC LIMIT 1")[0]["id"]
    c = client.get(f"/api/cycle/{cid}").json()
    assert len(c["profile"]) == pytest.approx(c["minutes"], abs=1)
    assert c["similar"] and all(s["id"] != cid for s in c["similar"])
    assert client.get("/api/cycle/999999").status_code == 404


def test_csv_opens_in_danish_excel(client):
    text = client.get("/api/export.csv").content.decode("utf-8")
    assert text.startswith("﻿Maskine;Start;")
    assert "Tørretumbler" in text


def test_reimport_needs_home_assistant(client):
    assert client.post("/api/reimport").status_code == 400

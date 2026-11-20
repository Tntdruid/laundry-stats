import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
import sensors
import stats
from collector import Collector
from config import load_settings
from hass import HomeAssistant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise one line per poll
log = logging.getLogger("main")

settings = load_settings()
STATIC = Path(__file__).parent / "static"
state = {"collector": None, "hass": None, "task": None, "reimport": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    machines = [m for m in settings.machines if m.power_entity]
    if settings.ha_enabled and machines:
        hass = HomeAssistant(settings.ha_url, settings.ha_token)
        collector = Collector(settings, hass)
        state.update(hass=hass, collector=collector, task=asyncio.create_task(collector.run()))
        log.info("watching %s every %ss", ", ".join(f"{m.name} ({m.power_entity})" for m in machines),
                 settings.poll_interval)
    else:
        log.warning("no Home Assistant connection or no machines set up - serving existing data only")
    yield
    if state["task"]:
        state["task"].cancel()
        await state["hass"].close()


app = FastAPI(lifespan=lifespan)


def scope(start: Optional[int], end: Optional[int], machine: Optional[str]) -> stats.Scope:
    return stats.Scope(start or 0, end or int(time.time()) + 60, machine or None)


@app.get("/api/meta")
def meta():
    c = state["collector"]
    return {
        "machines": [{"id": m.id, "name": m.name, "type": m.type, "power_entity": m.power_entity,
                      "start_watt": m.start_watt, "start_seconds": m.start_seconds, "stop_watt": m.stop_watt,
                      "stop_minutes": m.stop_minutes, "min_minutes": m.min_minutes, "skip_entity": m.skip_entity}
                     for m in settings.machines],
        "first_cycle": stats.first_cycle(),
        "price": {"entity": settings.price_entity or None, "fixed": settings.price_per_kwh},
        "collector": {
            "enabled": c is not None,
            "last_poll": c.last_poll if c else None,
            "poll_interval": settings.poll_interval,
            "last_error": c.last_error if c else None,
            "importing": bool(c and c.importing) or bool(state["reimport"] and not state["reimport"].done()),
            "import_days": settings.import_days,
        },
        "home_assistant": {**sensors.status, "available": settings.ha_enabled, "sensors_enabled": settings.ha_sensors,
                           "event": sensors.EVENT, "notify_services": settings.notify_services},
    }


@app.get("/api/live")
def live():
    c = state["collector"]
    out = []
    for m in settings.machines:
        lv = (c.live.get(m.id) if c else None) or {"running": False}
        out.append({"id": m.id, "name": m.name, "type": m.type, **lv})
    return out


@app.post("/api/reimport")
async def reimport():
    if not state["collector"]:
        raise HTTPException(400, "Ingen forbindelse til Home Assistant")
    if not state["reimport"] or state["reimport"].done():
        state["reimport"] = asyncio.create_task(state["collector"].reimport())
    return {"started": True}


@app.get("/api/latest")
def latest():
    """Cheap change marker; the page polls it and reloads its data when it moves."""
    row = db.query("SELECT MAX(id) AS id, COUNT(*) AS n FROM cycles")[0]
    return {"marker": f"{row['id']}-{row['n']}"}


@app.get("/api/summary")
def summary(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None):
    return stats.summary(scope(start, end, machine), settings.machines)


@app.get("/api/timeline")
def timeline(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None,
             bucket: str = Query("day", pattern="^(day|week|month)$")):
    return stats.timeline(scope(start, end, machine), bucket, settings.machines)


@app.get("/api/heatmap")
def heatmap(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None):
    return stats.heatmap(scope(start, end, machine))


@app.get("/api/durations")
def durations(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None):
    return stats.durations(scope(start, end, machine), settings.machines)


@app.get("/api/insights")
def insights(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None):
    return stats.insights(scope(start, end, machine), settings.machines)


@app.get("/api/cycles")
def cycles(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None,
           limit: int = Query(50, le=500)):
    return stats.recent(scope(start, end, machine), limit)


@app.get("/api/cycle/{cycle_id}")
def cycle(cycle_id: int):
    data = stats.detail(cycle_id)
    if not data:
        raise HTTPException(404, "Turen findes ikke")
    return data


@app.get("/api/export.csv")
def export(start: Optional[int] = None, end: Optional[int] = None, machine: Optional[str] = None):
    filename = f"vaskestatistik-{datetime.now():%Y-%m-%d}.csv"
    return Response(stats.export_csv(scope(start, end, machine), settings.machines),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

"""Reads each machine's power history from Home Assistant, stores the cycles it finds and keeps the live status.

Only one thing is remembered between polls: per machine, a moment it was known to be idle. Every poll reads the
history from there to now. So a restart of the add-on or of Home Assistant loses nothing, and the first start reads
the history Home Assistant still has (import_days) with the very same code.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional

import db
import detector
import sensors
from config import Machine, Settings

log = logging.getLogger("collector")

WINDOW = 86400  # read old history a day at a time
KNOWN = 40  # cycles the expected finish time learns from
ACTIVE = {"on", "active", "true", "home", "open"}


def duration_text(minutes: float) -> str:
    m = int(round(minutes))
    return (f"{m // 60} t " if m >= 60 else "") + f"{m % 60} min"


def decimal(n: float, digits: int = 2) -> str:
    return f"{n:.{digits}f}".replace(".", ",")


def known_cycles(machine_id: str, limit: int = KNOWN) -> list:
    rows = db.cycle_rows("SELECT id, started_at, minutes, profile FROM cycles WHERE machine = ? AND excluded = 0 "
                         "ORDER BY started_at DESC LIMIT ?", [machine_id, limit])
    return rows[::-1]


class Collector:
    def __init__(self, settings: Settings, hass):
        self.settings = settings
        self.hass = hass
        self.live: Dict[str, dict] = {m.id: {"running": False} for m in settings.machines}
        self.last_poll: Optional[float] = None
        self.last_error: Optional[str] = None
        self.importing = False
        self._sent: dict = {}
        self._last_full = 0.0

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
                self.last_error = None
            except Exception as e:
                if self.last_error != str(e):
                    log.warning("poll failed: %s", e)
                self.last_error = str(e)
            await asyncio.sleep(self.settings.poll_interval)

    async def poll(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        found = 0
        for m in self.settings.machines:
            found += await self.poll_machine(m, now)
        self.last_poll = now
        if self.settings.ha_sensors:
            await self.publish()
        return found

    async def poll_machine(self, m: Machine, now: float) -> int:
        key = f"resume:{m.id}"
        saved = db.get_meta(key)
        resume = float(saved) if saved else now - self.settings.import_days * 86400
        self.importing = now - resume > WINDOW
        found = 0
        end = min(now, resume + WINDOW)
        while True:
            readings = await self.hass.history(m.power_entity, resume, end)
            result = detector.scan(m, readings, end, resume)
            live = end >= now and not self.importing
            for run in result.cycles:
                if await self.save(m, run, live=live and run.end > now - 3600):
                    found += 1
            if result.resume > resume:
                resume = result.resume
                db.set_meta(key, str(resume))
            if end >= now:
                break
            # a cycle running across the window's end is read again from its start, with the window grown
            end = min(now, max(end, resume) + WINDOW)
        self.importing = False
        self._set_live(m, result, now)
        if found:
            log.info("%s: %d new cycle(s)", m.name, found)
        return found

    async def save(self, m: Machine, run: detector.Run, live: bool) -> bool:
        c = detector.summarize(run)
        prices = []
        if self.settings.price_entity:
            try:
                prices = await self.hass.history(self.settings.price_entity, run.start, run.end)
            except Exception as e:
                log.warning("could not read the price from %s: %s", self.settings.price_entity, e)
        c["cost"], c["price"] = detector.cost(c["profile"], run.start, prices, self.settings.price_per_kwh)
        excluded = False
        if m.skip_entity:
            try:
                excluded = str(await self.hass.state_at(m.skip_entity, run.start + 1)).lower() in ACTIVE
            except Exception as e:
                log.warning("could not read %s: %s", m.skip_entity, e)
        c.update(machine=m.id, type=m.type, excluded=int(excluded), source="live" if live else "history")
        cycle_id = db.insert_cycle(c)
        if cycle_id and live and not excluded:
            await self.announce(m, c, cycle_id)
        return cycle_id is not None

    async def announce(self, m: Machine, c: dict, cycle_id: int) -> None:
        data = {"machine": m.name, "machine_id": m.id, "type": m.type, "cycle_id": cycle_id,
                "minutes": round(c["minutes"]), "kwh": c["kwh"], "cost": c["cost"],
                "started": datetime.fromtimestamp(c["started_at"]).isoformat(timespec="minutes")}
        message = (f"{m.name} er færdig. Den kørte {duration_text(c['minutes'])} og brugte "
                   f"{decimal(c['kwh'])} kWh ({decimal(c['cost'])} kr).")
        try:
            await self.hass.fire_event(sensors.EVENT, data)
            for service in self.settings.notify_services:
                service = service if "." in service else f"notify.{service}"
                await self.hass.call_service(service, {"title": m.name, "message": message})
        except Exception as e:
            log.warning("could not tell Home Assistant that %s is done: %s", m.name, e)

    def _set_live(self, m: Machine, result: detector.Scan, now: float) -> None:
        live = {"running": False, "watt": result.watt, "updated": now}
        if result.current:
            run = result.current
            so_far = detector.profile(run.readings, run.start, now) if run.readings else []
            guess = detector.expected(so_far, known_cycles(m.id))
            live.update(running=True, started_at=int(run.start), minutes=round(run.minutes),
                        kwh=round(detector.summarize(run)["kwh"], 3) if run.readings else 0)
            if guess:
                live.update(expected_minutes=guess["minutes"], expected_end=int(run.start + guess["minutes"] * 60),
                            like=guess["like"])
        self.live[m.id] = live

    async def publish(self) -> int:
        """Send the sensors that changed, and all of them every 10 minutes (Home Assistant forgets them on restart)."""
        full = time.time() - self._last_full > sensors.RESEND_ALL_EVERY
        sent = 0
        for entity_id, (state, attrs) in sensors.build(self.settings, self.live).items():
            if full or self._sent.get(entity_id) != (state, attrs):
                await self.hass.set_state(entity_id, state, attrs)
                self._sent[entity_id] = (state, attrs)
                sent += 1
        if full:
            self._last_full = time.time()
        sensors.status.update(last_update=time.time(), sensors=len(self._sent), entities=sorted(self._sent))
        return sent

    async def reimport(self) -> None:
        """Read the whole history window again (cycles already stored are skipped)."""
        db.delete_meta_like("resume:%")
        await self.poll()

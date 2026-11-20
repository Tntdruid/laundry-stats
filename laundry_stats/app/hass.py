"""Home Assistant's REST API: the power history the cycles are read from, and the sensors and messages sent back.

Reached via the Supervisor (`homeassistant_api: true` in config.yaml), so no MQTT broker is needed. Sensors set
this way are plain states: they are re-sent regularly, because Home Assistant forgets them when it restarts.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote

import httpx

from detector import Reading

log = logging.getLogger("hass")

UNAVAILABLE = {"unavailable", "unknown", "none", ""}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def number(state) -> Optional[float]:
    if state is None or str(state).strip().lower() in UNAVAILABLE:
        return None
    try:
        return float(state)
    except ValueError:
        return None


class HomeAssistant:
    def __init__(self, url: str, token: str, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.client = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=60,
                                        transport=transport)

    async def close(self) -> None:
        await self.client.aclose()

    def _check(self, r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise PermissionError("Home Assistant afviste forbindelsen – kræver homeassistant_api i add-on'et")
        r.raise_for_status()

    async def history(self, entity_id: str, start: float, end: float) -> List[Reading]:
        """Every state the entity had from start to end; the first one is the state it had at start."""
        r = await self.client.get(f"/history/period/{quote(iso(start))}", params={
            "filter_entity_id": entity_id, "end_time": iso(end),
            "minimal_response": "", "no_attributes": "", "significant_changes_only": "0"})
        self._check(r)
        rows = next(iter(r.json() or []), [])
        out = []
        for row in rows:
            t = row.get("last_changed") or row.get("last_updated")
            if t:
                out.append((max(parse_time(t), start), number(row.get("state"))))
        return out

    async def state(self, entity_id: str) -> Optional[str]:
        r = await self.client.get(f"/states/{entity_id}")
        if r.status_code == 404:
            return None
        self._check(r)
        return r.json().get("state")

    async def state_at(self, entity_id: str, ts: float) -> Optional[str]:
        r = await self.client.get(f"/history/period/{quote(iso(ts))}", params={
            "filter_entity_id": entity_id, "end_time": iso(ts + 1), "minimal_response": "", "no_attributes": ""})
        self._check(r)
        rows = next(iter(r.json() or []), [])
        return rows[0].get("state") if rows else None

    async def set_state(self, entity_id: str, state, attributes: dict) -> None:
        r = await self.client.post(f"/states/{entity_id}", json={"state": str(state)[:255], "attributes": attributes})
        self._check(r)

    async def call_service(self, service: str, data: dict) -> None:
        domain, _, name = service.partition(".")
        r = await self.client.post(f"/services/{domain}/{name}", json=data)
        self._check(r)

    async def fire_event(self, event_type: str, data: dict) -> None:
        r = await self.client.post(f"/events/{event_type}", json=data)
        self._check(r)

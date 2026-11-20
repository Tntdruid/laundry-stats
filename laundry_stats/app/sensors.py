"""Sensors published to Home Assistant, one set per machine (sensor.laundry_stats_<machine>_...)."""
from datetime import datetime, timezone

import db

PREFIX = "sensor.laundry_stats"
EVENT = "laundry_stats_cycle_finished"
RESEND_ALL_EVERY = 10 * 60
TYPE_ICON = {"washer": "mdi:washing-machine", "dryer": "mdi:tumble-dryer"}

status = {"last_update": None, "sensors": 0, "entities": []}


def _iso(ts) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _totals(machine_id: str, since: float) -> dict:
    row = db.query("SELECT COUNT(*) AS n, COALESCE(SUM(kwh), 0) AS kwh, COALESCE(SUM(cost), 0) AS cost FROM cycles "
                   "WHERE machine = ? AND excluded = 0 AND started_at >= ?", [machine_id, int(since)])[0]
    return row


def build(settings, live: dict) -> dict:
    """entity_id -> (state, attributes)."""
    now = datetime.now()
    midnight = datetime(now.year, now.month, now.day).timestamp()
    month = datetime(now.year, now.month, 1).timestamp()
    out = {}
    for m in settings.machines:
        base = f"{PREFIX}_{m.id}"
        icon = TYPE_ICON[m.type]
        lv = live.get(m.id) or {}
        running = bool(lv.get("running"))
        out[f"{base}_status"] = ("running" if running else "idle", {
            "friendly_name": f"{m.name} status", "icon": icon, "power": lv.get("watt"),
            "started": _iso(lv["started_at"]) if running else None,
            "minutes": lv.get("minutes") if running else None,
            "expected_minutes": lv.get("expected_minutes") if running else None,
            "expected_end": _iso(lv["expected_end"]) if running and lv.get("expected_end") else None})
        out[f"{base}_expected_finish"] = (
            _iso(lv["expected_end"]) if running and lv.get("expected_end") else "unknown",
            {"friendly_name": f"{m.name} forventet færdig", "device_class": "timestamp", "icon": "mdi:timer-sand"})
        today, this_month = _totals(m.id, midnight), _totals(m.id, month)
        word = "vaske" if m.type == "washer" else "tørringer"
        out[f"{base}_cycles_today"] = (today["n"], {
            "friendly_name": f"{m.name} i dag", "unit_of_measurement": word, "icon": icon, "state_class": "measurement"})
        out[f"{base}_cycles_month"] = (this_month["n"], {
            "friendly_name": f"{m.name} denne måned", "unit_of_measurement": word, "icon": icon,
            "state_class": "measurement"})
        out[f"{base}_energy_month"] = (round(this_month["kwh"], 2), {
            "friendly_name": f"{m.name} strøm denne måned", "unit_of_measurement": "kWh", "device_class": "energy",
            "icon": "mdi:lightning-bolt"})
        out[f"{base}_cost_month"] = (round(this_month["cost"], 2), {
            "friendly_name": f"{m.name} pris denne måned", "unit_of_measurement": "kr", "icon": "mdi:cash"})
        last = db.query("SELECT started_at, minutes, kwh, cost FROM cycles WHERE machine = ? AND excluded = 0 "
                        "ORDER BY started_at DESC LIMIT 1", [m.id])
        if last:
            r = last[0]
            out[f"{base}_last_cycle"] = (round(r["minutes"]), {
                "friendly_name": f"{m.name} sidste tur", "unit_of_measurement": "min", "device_class": "duration",
                "icon": "mdi:history", "started": _iso(r["started_at"]), "kwh": r["kwh"], "cost": r["cost"]})
    return out

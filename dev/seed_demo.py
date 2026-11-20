"""Fill dev/data with four months of demo laundry, read through the real collector from a fake Home Assistant.

    .venv/Scripts/python dev/seed_demo.py
"""
import asyncio
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "laundry_stats" / "app"))
sys.path.insert(0, str(ROOT / "dev"))
os.environ.setdefault("DATA_DIR", str(ROOT / "dev" / "data"))

import demo_data  # noqa: E402
from fake_ha import FakeHA  # noqa: E402

DAYS = 120
PRICE = "sensor.elpris"
SKIP = "timer.vaskemaskine_afkalkning"


def demo_settings():
    from config import DEFAULT_MACHINES, Settings, parse_machines
    machines = [dict(m) for m in DEFAULT_MACHINES]
    machines[0]["skip_entity"] = SKIP
    return Settings(machines=parse_machines(machines), price_entity=PRICE, import_days=DAYS + 1,
                    notify_services=["notify.mobile_app_demo"])


def demo_ha(now: float) -> FakeHA:
    """The household's history up to today, plus a 60° wash that started 35 minutes ago."""
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    washer, dryer, prices = demo_data.household(today - DAYS * 86400, DAYS)
    washer = [r for r in washer if r[0] < now - 4 * 3600]
    dryer = [r for r in dryer if r[0] < now - 4 * 3600]
    running = demo_data.wash(now - 35 * 60, demo_data.WASH_PROGRAMS["60°"], random.Random(1))
    washer += [r for r in running if r[0] <= now]
    prices += [(today + h * 3600, 2.1) for h in range(24)]
    descaling_day = today - 20 * 86400  # a descaling program that shouldn't count as laundry
    descale = demo_data.wash(descaling_day + 14 * 3600, demo_data.WASH_PROGRAMS["Bomuld 90°"], random.Random(2))
    washer = sorted(r for r in washer if not descaling_day + 13 * 3600 < r[0] < descaling_day + 17 * 3600) + descale
    return FakeHA({"sensor.vaskemaskine_power": sorted(washer), "sensor.torretumbler_power": dryer, PRICE: prices},
                  {SKIP: lambda ts: "active" if descaling_day + 13.5 * 3600 < ts < descaling_day + 17 * 3600 else "idle"})


async def fill(now: float):
    import db
    from collector import Collector
    db.connect()
    collector = Collector(demo_settings(), demo_ha(now))
    found = await collector.poll(now)
    return collector, found


if __name__ == "__main__":
    data = Path(os.environ["DATA_DIR"])
    data.mkdir(parents=True, exist_ok=True)
    for f in data.glob("laundry_stats.db*"):
        f.unlink()
    _, found = asyncio.run(fill(time.time()))
    print(f"{found} ture gemt i {data}")

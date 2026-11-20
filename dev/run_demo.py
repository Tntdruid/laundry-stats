"""Run the dashboard locally against dev/data (fill it first with dev/seed_demo.py).

    .venv/Scripts/python dev/run_demo.py

Without HA_URL/HA_TOKEN it shows a fake Home Assistant, where the washer is halfway through a 60° wash.
With them set, it reads your real machines instead.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "laundry_stats" / "app"
os.environ.setdefault("DATA_DIR", str(ROOT / "dev" / "data"))
os.chdir(APP)
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "dev"))

import uvicorn  # noqa: E402

import main  # noqa: E402

if not main.settings.ha_enabled:
    import seed_demo
    collector, _ = asyncio.run(seed_demo.fill(time.time()))
    main.settings = collector.settings
    main.state["collector"] = collector

uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("PORT", 8099)))

"""Point the app at a throw-away data folder filled with the demo data, before any app module is imported."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "laundry_stats" / "app"

DATA = tempfile.mkdtemp(prefix="laundry-stats-test-")
os.environ["DATA_DIR"] = DATA
os.environ["DB_DIR"] = DATA
for key in ("HA_URL", "HA_TOKEN", "SUPERVISOR_TOKEN", "MACHINES"):  # the app must not try to reach a real HA
    os.environ.pop(key, None)

subprocess.run([sys.executable, str(ROOT / "dev" / "seed_demo.py")], check=True, env=os.environ, capture_output=True)
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "dev"))

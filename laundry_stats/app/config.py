"""Settings come from Home Assistant's /data/options.json, with env vars as fallback for local dev."""
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
# The add-on's public config folder (map: addon_config), visible as addon_configs/<slug> over Samba.
# Falls back to DATA_DIR when it isn't mounted, e.g. in local development.
DB_DIR = Path(os.environ.get("DB_DIR") or ("/config" if os.path.isdir("/config") else DATA_DIR))

TYPES = ("washer", "dryer")


def slug(name: str) -> str:
    name = name.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "maskine"


@dataclass
class Machine:
    """One appliance on a smart plug, and how its power readings turn into cycles.

    A cycle starts when the power has been above start_watt for start_seconds, and ends when it has been below
    stop_watt for stop_minutes. Runs shorter than min_minutes (a cancelled program) are not counted.
    """
    name: str
    type: str = "washer"
    power_entity: str = ""
    start_watt: float = 50
    start_seconds: int = 0
    stop_watt: float = 45
    stop_minutes: float = 4
    min_minutes: float = 15
    # while this entity is on/active (e.g. a timer for descaling), new cycles are kept out of the statistics
    skip_entity: str = ""
    id: str = ""

    def __post_init__(self):
        self.id = self.id or slug(self.name)
        if self.type not in TYPES:
            self.type = "washer"


DEFAULT_MACHINES = [
    {"name": "Vaskemaskine", "type": "washer", "power_entity": "sensor.vaskemaskine_power",
     "start_watt": 50, "start_seconds": 0, "stop_watt": 45, "stop_minutes": 4, "min_minutes": 15},
    {"name": "Tørretumbler", "type": "dryer", "power_entity": "sensor.torretumbler_power",
     "start_watt": 100, "start_seconds": 60, "stop_watt": 35, "stop_minutes": 2, "min_minutes": 15},
]


@dataclass
class Settings:
    machines: List[Machine] = field(default_factory=list)
    # a sensor with the electricity price in kr/kWh (e.g. Energi Data Service or Nord Pool); empty = fixed price
    price_entity: str = ""
    price_per_kwh: float = 2.5
    poll_interval: int = 30
    # how far back the first start looks in Home Assistant's history (the recorder keeps 10 days by default)
    import_days: int = 30
    ha_sensors: bool = True
    # e.g. ["notify.mobile_app_phone"]; empty = no message when a cycle is done
    notify_services: List[str] = field(default_factory=list)
    # Home Assistant Core API: the Supervisor's proxy in the add-on, HA_URL/HA_TOKEN in local development
    ha_url: str = ""
    ha_token: str = ""

    @property
    def ha_enabled(self) -> bool:
        return bool(self.ha_url and self.ha_token)

    def machine(self, machine_id: str):
        return next((m for m in self.machines if m.id == machine_id), None)


def parse_machines(raw) -> List[Machine]:
    fields = Machine.__dataclass_fields__
    out, seen = [], set()
    for entry in raw or []:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            continue
        m = Machine(**{k: v for k, v in entry.items() if k in fields and v is not None})
        m.name = m.name.strip()
        m.power_entity = str(m.power_entity or "").strip()
        m.skip_entity = str(m.skip_entity or "").strip()
        while m.id in seen:  # two machines with the same name
            m.id += "_2"
        seen.add(m.id)
        out.append(m)
    return out


def load_settings() -> Settings:
    options = {}
    options_file = DATA_DIR / "options.json"
    if options_file.exists():
        options = json.loads(options_file.read_text(encoding="utf-8"))

    def pick(key, default):
        value = options.get(key)
        return value if value not in (None, "") else os.environ.get(key.upper()) or default

    def flag(key, default: bool) -> bool:
        """Booleans can't use pick(): an option set to false must stay false."""
        if key in options:
            return bool(options[key])
        env = os.environ.get(key.upper())
        return env.strip().lower() in ("1", "true", "yes", "on") if env is not None else default

    machines = options.get("machines")
    if machines is None:
        machines = json.loads(os.environ["MACHINES"]) if os.environ.get("MACHINES") else DEFAULT_MACHINES
    notify = options.get("notify_services")
    if notify is None:
        notify = [s for s in os.environ.get("NOTIFY_SERVICES", "").split(",")]

    supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")
    return Settings(
        machines=parse_machines(machines),
        price_entity=str(pick("price_entity", "")).strip(),
        price_per_kwh=float(pick("price_per_kwh", 2.5)),
        poll_interval=int(pick("poll_interval", 30)),
        import_days=int(pick("import_days", 30)),
        ha_sensors=flag("ha_sensors", True),
        notify_services=[str(s).strip() for s in notify if str(s).strip()],
        ha_url=os.environ.get("HA_URL", "http://supervisor/core/api" if supervisor_token else "").rstrip("/"),
        ha_token=os.environ.get("HA_TOKEN", supervisor_token),
    )

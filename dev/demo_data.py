"""Made-up but realistic smart plug readings for a washer and a dryer, used by the demo and the tests.

The washer programs are minute-by-minute patterns measured on a real machine:
H = heating (~2 kW), S = spinning, t = drum turning, _ = still.
"""
import random

WASH_PROGRAMS = {
    "40° kort": "ttSHHHHHHHHttttttttttttttttttttStttttttttSt_ttttttSSSSt___",
    "40°": "ttSHHHHHHHHHHHHHHHHtttttttttttttttttttt_tttttttttttt_tttttttSSSS___",
    "60°": "tttHHHHHHHHHHHHHHHHHHHHHHHHHStttttttttttttttttttttttttttttttttttttttSt_ttttttttttttttttSSSSS_____",
    "Bomuld 90°": "tttHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHttttttttttttttttttttt_tttt"
                  "_tttttttttttttttSt_ttttttttttttttttSSSSt___",
    "Uld kold": "SHtttttttttttttttttttttttttttttttttttttttttttttttttt_tSt__tttttttttttttttttttttttttttt__SSSSS___",
}
WASH_WEIGHTS = [3, 5, 3, 1, 1]
DRY_MINUTES = (100, 118)


def _watt(c: str, rnd: random.Random) -> float:
    if c == "H":
        return rnd.uniform(1900, 2150)
    if c == "S":
        return rnd.uniform(250, 520)
    if c == "t":
        return rnd.choice([rnd.uniform(60, 180), rnd.uniform(8, 20)])  # the drum turns, stops, turns
    return rnd.uniform(1, 3)


def wash(start: float, pattern: str, rnd: random.Random, step: int = 10):
    """Readings every `step` seconds through a wash, then the low ticking after spinning, then off."""
    out = [(start - 60, 1.0)]
    t = start
    for c in pattern.rstrip("_"):
        for _ in range(60 // step):
            out.append((t, round(_watt(c, rnd), 1)))
            t += step
    for _ in range(8 * 60 // step):  # ticks with up to ~38 W for about 8 minutes, below the 45 W stop level
        out.append((t, round(rnd.choice([2.0, rnd.uniform(20, 38)]), 1)))
        t += step
    out.append((t, 0.0))
    return out


def dry(start: float, minutes: int, rnd: random.Random, crease_minutes: int = 30, step: int = 10):
    """A dryer run (200-934 W), then anti-crease bursts of ~30 s at 134 W every 3.5 minutes."""
    out = [(start - 60, 0.0)]
    t = start
    for _ in range(minutes * 60 // step):
        out.append((t, round(rnd.uniform(200, 934), 1)))
        t += step
    out.append((t, 0.0))
    end = t
    while t < end + crease_minutes * 60:
        t += 210
        out += [(t, 134.0), (t + 30, 0.0)]
    return out


def household(start_day: float, days: int, seed: int = 7):
    """Washer and dryer readings for a household over some days: (washer_readings, dryer_readings, price_readings)."""
    rnd = random.Random(seed)
    washer, dryer, prices = [], [], []
    dryer_free = 0.0
    for d in range(days):
        day = start_day + d * 86400
        for h in range(24):  # hourly price, cheapest at night
            base = 1.6 + (0.9 if 17 <= h <= 20 else 0.4 if 7 <= h <= 16 else 0)
            prices.append((day + h * 3600, round(base + rnd.uniform(-0.3, 0.3), 2)))
        n = rnd.choices([0, 1, 2], weights=[4 if d % 7 < 5 else 1, 4, 2 if d % 7 >= 5 else 1])[0]
        t = day + rnd.choice([7, 8, 9, 10, 18, 19]) * 3600 + rnd.randint(0, 3000)
        for _ in range(n):
            program = rnd.choices(list(WASH_PROGRAMS), weights=WASH_WEIGHTS)[0]
            w = wash(t, WASH_PROGRAMS[program], rnd)
            washer += w
            t = w[-1][0]
            if rnd.random() < 0.7:
                wait = rnd.choice([rnd.randint(2, 40), rnd.randint(40, 200)]) * 60
                dr = dry(max(t + wait, dryer_free + 120), rnd.randint(*DRY_MINUTES), rnd)
                dryer += dr
                dryer_free = dr[-1][0]
                t = max(t + rnd.randint(5, 30) * 60, dr[0][0] + 60)
            else:
                t += rnd.randint(10, 60) * 60
    return sorted(washer), sorted(dryer), prices

"""Statistics over the stored cycles. Few enough rows (a few a day) that it's all done in Python, in local time."""
import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import List, Optional

import db
import detector

PAIR_HOURS = 12  # a dryer run this soon after a wash is taken to be that wash being dried
DAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


@dataclass
class Scope:
    start: int
    end: int
    machine: Optional[str] = None

    def previous(self) -> "Scope":
        length = self.end - self.start
        return Scope(self.start - length, self.start, self.machine)


def cycles(sc: Scope, any_machine: bool = False, profile: bool = False) -> List[dict]:
    cols = "*" if profile else ("id, machine, type, started_at, ended_at, minutes, kwh, cost, price, peak_w, "
                                "heat_minutes, heat_kwh, source")
    sql = f"SELECT {cols} FROM cycles WHERE excluded = 0 AND started_at >= ? AND started_at < ?"
    params = [sc.start, sc.end]
    if sc.machine and not any_machine:
        sql += " AND machine = ?"
        params.append(sc.machine)
    return db.cycle_rows(sql + " ORDER BY started_at", params)


def first_cycle() -> Optional[int]:
    return db.query("SELECT MIN(started_at) AS t FROM cycles WHERE excluded = 0")[0]["t"]


def pairs(rows: List[dict]) -> List[dict]:
    """Each dryer run matched to the latest unmatched wash that ended before it, within PAIR_HOURS."""
    washes = [r for r in rows if r["type"] == "washer"]
    used, out = set(), []
    for d in (r for r in rows if r["type"] == "dryer"):
        before = [w for w in washes if w["id"] not in used and w["ended_at"] <= d["started_at"]
                  and d["started_at"] - w["ended_at"] <= PAIR_HOURS * 3600]
        if before:
            w = before[-1]
            used.add(w["id"])
            out.append({"wash": w, "dry": d, "wait": (d["started_at"] - w["ended_at"]) / 60})
    return out


def _totals(rows: List[dict]) -> dict:
    n = len(rows)
    return {"n": n, "minutes": sum(r["minutes"] for r in rows), "kwh": sum(r["kwh"] for r in rows),
            "cost": sum(r["cost"] or 0 for r in rows),
            "avg_minutes": sum(r["minutes"] for r in rows) / n if n else 0,
            "avg_kwh": sum(r["kwh"] for r in rows) / n if n else 0,
            "avg_cost": sum(r["cost"] or 0 for r in rows) / n if n else 0}


def _summary(sc: Scope, machines) -> dict:
    everything = cycles(sc, any_machine=True)
    rows = [r for r in everything if not sc.machine or r["machine"] == sc.machine]
    per_machine = []
    for m in machines:
        mine = [r for r in rows if r["machine"] == m.id]
        if sc.machine and m.id != sc.machine:
            continue
        per_machine.append({"id": m.id, "name": m.name, "type": m.type, **_totals(mine)})
    known = {m.id for m in machines}
    orphans = [r for r in rows if r["machine"] not in known]  # machines since removed from the configuration
    if orphans:
        per_machine.append({"id": "_other", "name": "Andre", "type": "washer", **_totals(orphans)})
    p = pairs(everything)
    washes = [r for r in everything if r["type"] == "washer"]
    days = max(1, (min(sc.end, int(datetime.now().timestamp())) - max(sc.start, first_cycle() or sc.start)) / 86400)
    return {
        **_totals(rows),
        "washes": sum(1 for r in rows if r["type"] == "washer"),
        "dries": sum(1 for r in rows if r["type"] == "dryer"),
        "machines": per_machine,
        "per_week": len(rows) / days * 7,
        "dried_share": len(p) / len(washes) if washes else None,
        "wait_median": median(x["wait"] for x in p) if p else None,
        "heat_share": (sum(r["heat_kwh"] or 0 for r in washes) / sum(r["kwh"] for r in washes))
        if washes and sum(r["kwh"] for r in washes) else None,
    }


def summary(sc: Scope, machines) -> dict:
    out = _summary(sc, machines)
    out["previous"] = _summary(sc.previous(), machines) if sc.start > 0 else None
    out["excluded"] = db.query("SELECT COUNT(*) AS n FROM cycles WHERE excluded = 1 AND started_at >= ? AND "
                               "started_at < ?", [sc.start, sc.end])[0]["n"]
    return out


def _bucket(ts: int, bucket: str) -> date:
    d = datetime.fromtimestamp(ts).date()
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def _next(d: date, bucket: str) -> date:
    if bucket == "day":
        return d + timedelta(days=1)
    if bucket == "week":
        return d + timedelta(days=7)
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def timeline(sc: Scope, bucket: str, machines) -> dict:
    rows = cycles(sc)
    if not rows:
        return {"buckets": [], "machines": []}
    start = _bucket(max(sc.start, rows[0]["started_at"]), bucket)
    end = _bucket(min(sc.end, int(datetime.now().timestamp())), bucket)
    keys = []
    d = start
    while d <= end:
        keys.append(d)
        d = _next(d, bucket)
    index = {k: i for i, k in enumerate(keys)}
    names = {m.id: m for m in machines}
    series = {}
    for r in rows:
        s = series.setdefault(r["machine"], {
            "id": r["machine"], "name": names[r["machine"]].name if r["machine"] in names else r["machine"],
            "type": r["type"], "n": [0] * len(keys), "kwh": [0.0] * len(keys), "cost": [0.0] * len(keys),
            "minutes": [0.0] * len(keys)})
        i = index.get(_bucket(r["started_at"], bucket))
        if i is None:
            continue
        s["n"][i] += 1
        s["kwh"][i] = round(s["kwh"][i] + r["kwh"], 3)
        s["cost"][i] = round(s["cost"][i] + (r["cost"] or 0), 2)
        s["minutes"][i] += r["minutes"]
    return {"buckets": [k.isoformat() for k in keys], "machines": list(series.values())}


def heatmap(sc: Scope) -> list:
    """[weekday (0 = Monday), hour, starts]"""
    c = Counter()
    for r in cycles(sc):
        t = datetime.fromtimestamp(r["started_at"])
        c[(t.weekday(), t.hour)] += 1
    return [[d, h, n] for (d, h), n in sorted(c.items())]


def durations(sc: Scope, machines) -> dict:
    """Minutes per cycle in 10-minute bins, per machine."""
    rows = cycles(sc)
    if not rows:
        return {"bins": [], "machines": []}
    top = int(max(r["minutes"] for r in rows) // 10) + 1
    bins = [f"{i * 10}-{i * 10 + 9}" for i in range(top)]
    names = {m.id: m.name for m in machines}
    out = {}
    for r in rows:
        s = out.setdefault(r["machine"], {"id": r["machine"], "name": names.get(r["machine"], r["machine"]),
                                          "type": r["type"], "counts": [0] * top})
        s["counts"][int(r["minutes"] // 10)] += 1
    return {"bins": bins, "machines": list(out.values())}


def recent(sc: Scope, limit: int = 50) -> list:
    rows = db.query("SELECT id, machine, type, started_at, ended_at, minutes, kwh, cost, heat_minutes, excluded, "
                    "source FROM cycles WHERE started_at >= ? AND started_at < ?"
                    + (" AND machine = ?" if sc.machine else "") + " ORDER BY started_at DESC LIMIT ?",
                    [sc.start, sc.end] + ([sc.machine] if sc.machine else []) + [limit])
    return rows


def detail(cycle_id: int) -> Optional[dict]:
    rows = db.cycle_rows("SELECT * FROM cycles WHERE id = ?", [cycle_id])
    if not rows:
        return None
    c = rows[0]
    others = db.cycle_rows("SELECT id, started_at, minutes, kwh, cost, profile FROM cycles WHERE machine = ? "
                           "AND id != ? AND excluded = 0", [c["machine"], cycle_id])
    for o in others:
        o["distance"] = detector.distance(c["profile"], o["profile"]) + abs(c["minutes"] - o["minutes"]) * 5
    similar = sorted(others, key=lambda o: o["distance"])[:5]
    nearby = db.cycle_rows(
        "SELECT id, machine, type, started_at, ended_at, minutes, kwh, cost FROM cycles WHERE excluded = 0 AND "
        "started_at BETWEEN ? AND ? ORDER BY started_at",
        [c["started_at"] - 2 * PAIR_HOURS * 3600, c["ended_at"] + 2 * PAIR_HOURS * 3600])
    pair = next((p for p in pairs(nearby) if cycle_id in (p["wash"]["id"], p["dry"]["id"])), None)
    return {**c, "similar": similar, "pair": pair}


def _when(ts: int) -> str:
    t = datetime.fromtimestamp(ts)
    return f"{t.day}/{t.month} kl. {t.hour}.{t.minute:02d}"


def _dk(n: float, d: int = 0) -> str:
    return f"{n:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _duration(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60} t {m % 60} min" if m >= 60 else f"{m} min"


def insights(sc: Scope, machines) -> list:
    rows = cycles(sc)
    out = []
    if not rows:
        return out
    names = {m.id: m.name for m in machines}

    by_day = Counter(datetime.fromtimestamp(r["started_at"]).weekday() for r in rows)
    day, n = by_day.most_common(1)[0]
    if len(rows) >= 5:
        out.append({"icon": "calendar", "text": f"Travleste ugedag er {DAYS[day]} med {_dk(n / len(rows) * 100)} % "
                                                 f"af turene."})
    hours = Counter(datetime.fromtimestamp(r["started_at"]).hour for r in rows)
    hour, _ = hours.most_common(1)[0]
    out.append({"icon": "clock", "text": f"Flest ture startes mellem kl. {hour} og {hour + 1}."})

    p = pairs(cycles(sc, any_machine=True))
    if len(p) >= 3:
        wait = median(x["wait"] for x in p)
        out.append({"icon": "wait", "text": f"Vasketøjet venter typisk {_duration(wait)} i vaskemaskinen, før det "
                                             f"kommer i tørretumbleren."})
        longest = max(p, key=lambda x: x["wait"])
        if longest["wait"] >= 120:
            out.append({"icon": "sleep", "text": f"Længst ventetid: {_dk(longest['wait'] / 60, 1)} timer efter "
                                                  f"vasken {_when(longest['wash']['started_at'])}."})

    priciest = max(rows, key=lambda r: r["cost"] or 0)
    if priciest["cost"]:
        out.append({"icon": "cash", "text": f"Dyreste tur: {names.get(priciest['machine'], priciest['machine'])} "
                                             f"{_when(priciest['started_at'])} – {_dk(priciest['cost'], 2)} kr "
                                             f"({_dk(priciest['minutes'])} min, {_dk(priciest['kwh'], 2)} kWh)."})

    washes = [r for r in rows if r["type"] == "washer"]
    if washes and sum(r["kwh"] for r in washes):
        share = sum(r["heat_kwh"] or 0 for r in washes) / sum(r["kwh"] for r in washes)
        if share > 0.2:
            out.append({"icon": "fire", "text": f"{_dk(share * 100)} % af vaskemaskinens strøm går til at varme "
                                                 f"vand op. Koldere vaske er den største besparelse."})
        cold = [r for r in washes if not r["heat_minutes"]]
        if cold and len(cold) < len(washes):
            hot = [r for r in washes if r["heat_minutes"]]
            out.append({"icon": "drop", "text": f"En vask med opvarmning bruger i snit "
                                                 f"{_dk(sum(r['kwh'] for r in hot) / len(hot), 2)} kWh, en uden "
                                                 f"{_dk(sum(r['kwh'] for r in cold) / len(cold), 2)} kWh."})

    prices = [r["price"] for r in rows if r["price"]]
    if prices and max(prices) - min(prices) > 0.3:
        cheap = min(rows, key=lambda r: r["price"] or 99)
        out.append({"icon": "bolt", "text": f"Billigste strøm: {_dk(cheap['price'], 2)} kr/kWh "
                                             f"{_when(cheap['started_at'])}. Gennemsnittet var "
                                             f"{_dk(sum(prices) / len(prices), 2)} kr/kWh."})

    starts = sorted({datetime.fromtimestamp(r["started_at"]).date() for r in rows})
    gaps = [(b - a).days for a, b in zip(starts, starts[1:])]
    if gaps and max(gaps) >= 4:
        out.append({"icon": "pause", "text": f"Længste pause uden vasketøj: {max(gaps)} dage."})

    for m in machines:
        acc = detector.accuracy(db.cycle_rows(
            "SELECT id, minutes, profile FROM cycles WHERE machine = ? AND excluded = 0 ORDER BY started_at DESC "
            "LIMIT 40", [m.id])[::-1])
        if acc:
            out.append({"icon": "timer", "text": f"{m.name}: forventet færdig-tid rammer typisk inden for "
                                                  f"{acc['median_error']} min, gættet {acc['at_minute']} min inde."})
    return out


def export_csv(sc: Scope, machines) -> str:
    names = {m.id: m.name for m in machines}
    buf = io.StringIO()
    buf.write("﻿")  # BOM, so Excel reads it as UTF-8
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Maskine", "Start", "Slut", "Minutter", "kWh", "Pris (kr)", "kr/kWh", "Varme (min)", "Udeladt"])
    for r in db.query("SELECT * FROM cycles WHERE started_at >= ? AND started_at < ?"
                      + (" AND machine = ?" if sc.machine else "") + " ORDER BY started_at",
                      [sc.start, sc.end] + ([sc.machine] if sc.machine else [])):
        w.writerow([names.get(r["machine"], r["machine"]),
                    datetime.fromtimestamp(r["started_at"]).strftime("%d-%m-%Y %H:%M"),
                    datetime.fromtimestamp(r["ended_at"]).strftime("%d-%m-%Y %H:%M"),
                    _dk(r["minutes"]), _dk(r["kwh"], 3), _dk(r["cost"] or 0, 2), _dk(r["price"] or 0, 2),
                    r["heat_minutes"] or 0, "ja" if r["excluded"] else ""])
    return buf.getvalue()

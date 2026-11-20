"""Finds wash and dry cycles in a smart plug's power readings, and guesses when a running one is done.

Everything here is pure: readings in, cycles out. The collector feeds it Home Assistant's history, and the same
code reads both the old history on first start and the new readings every poll.

Readings are a step function: a plug reports a new value when the power changes, and the value holds until the
next one. A cycle starts when the power has been above start_watt for start_seconds (a dryer's anti-crease
tumbling after the program is short bursts, so a minute keeps them from counting), and ends when it has been
below stop_watt for stop_minutes (a washer pauses between rinses, and ticks at low power after spinning).
"""
import math
from dataclasses import dataclass, field
from statistics import median
from typing import List, Optional, Sequence, Tuple

Reading = Tuple[float, Optional[float]]  # (unix seconds, watt); None = plug unavailable, the last value holds

HEAT_WATT = 1000  # above this a washer is heating water; a dryer's heater is counted the same way
MAX_HOURS = 12  # a "cycle" longer than this is a plug that never went quiet, not laundry


@dataclass
class Run:
    start: float
    end: float
    readings: List[Reading]  # from start; the first one is at start

    @property
    def minutes(self) -> float:
        return (self.end - self.start) / 60


@dataclass
class Scan:
    cycles: List[Run] = field(default_factory=list)
    current: Optional[Run] = None  # a cycle still running at `now`; its end is `now`
    resume: float = 0.0  # a moment the machine was idle: scan from here next time and nothing is missed
    watt: Optional[float] = None  # latest reading
    too_short: int = 0
    abandoned: int = 0


def scan(machine, readings: Sequence[Reading], now: float, since: float) -> Scan:
    """Walk the readings from `since` (when the machine is known to be idle) up to `now`."""
    stop_s = machine.stop_minutes * 60
    out = Scan(resume=since)
    running = False
    start = above_since = below_since = None
    buf: List[Reading] = []
    value = None

    def finish(end: float) -> None:
        nonlocal running, start, below_since, above_since, buf
        run = Run(start, end, [r for r in buf if r[0] < end] or [(start, value)])
        if run.minutes >= machine.min_minutes:
            out.cycles.append(run)
        else:
            out.too_short += 1
        running, start, below_since, above_since, buf = False, None, None, None, []
        out.resume = max(out.resume, end + stop_s)

    def tick(t: float) -> None:
        """Let time pass up to t with the current value, firing the start and stop timers."""
        nonlocal running, start, above_since, below_since, buf
        if not running and above_since is not None and t - above_since >= machine.start_seconds:
            running, start, below_since = True, above_since, None
        if running and below_since is not None and t - below_since >= stop_s:
            finish(below_since)
        elif running and t - start > MAX_HOURS * 3600:
            out.abandoned += 1
            running, start, below_since, above_since, buf = False, None, None, None, []
            out.resume = t

    for t, w in readings:
        if t < since:
            t = since
        tick(t)
        if w is None:
            continue
        value = w
        if running:
            buf.append((t, w))
            if w < machine.stop_watt:
                below_since = below_since if below_since is not None else t
            else:
                below_since = None
        elif w > machine.start_watt:
            if above_since is None:
                above_since, buf = t, []
            buf.append((t, w))
            tick(t)  # start_seconds = 0 starts right away
        else:
            above_since, buf = None, []
            out.resume = max(out.resume, t)
    tick(now)

    out.watt = value
    if running:
        out.current = Run(start, now, list(buf))
    return out


# --- what a cycle looked like ----------------------------------------------------

def _pieces(readings: Sequence[Reading], start: float, end: float):
    """(from, to, watt) pieces of the step function between start and end."""
    pts = [(t, w) for t, w in readings if w is not None]
    for i, (t, w) in enumerate(pts):
        t0 = max(t, start)
        t1 = min(pts[i + 1][0] if i + 1 < len(pts) else end, end)
        if t1 > t0:
            yield t0, t1, w


def profile(readings: Sequence[Reading], start: float, end: float) -> List[int]:
    """Average watt for each minute of the cycle."""
    n = max(1, math.ceil((end - start) / 60))
    acc = [0.0] * n
    for t0, t1, w in _pieces(readings, start, end):
        while t0 < t1:
            m = min(int((t0 - start) // 60), n - 1)
            edge = min(t1, start + (m + 1) * 60) if m < n - 1 else t1
            acc[m] += w * (edge - t0)
            t0 = edge
    out = []
    for m, a in enumerate(acc):
        length = min(60.0, end - (start + 60 * m))
        out.append(round(a / length) if length > 0 else 0)
    return out


def summarize(run: Run) -> dict:
    prof = profile(run.readings, run.start, run.end)
    wh = sum(w * (t1 - t0) for t0, t1, w in _pieces(run.readings, run.start, run.end)) / 3600
    heat = [w for w in prof if w > HEAT_WATT]
    return {
        "started_at": int(run.start),
        "ended_at": int(run.end),
        "minutes": round(run.minutes, 1),
        "kwh": round(wh / 1000, 3),
        "peak_w": max((w for _, _, w in _pieces(run.readings, run.start, run.end)), default=0),
        "heat_minutes": len(heat),
        "heat_kwh": round(sum(heat) / 60 / 1000, 3),
        "profile": prof,
    }


def cost(prof: Sequence[int], start: float, prices: Sequence[Reading], fallback: float) -> Tuple[float, float]:
    """(kroner, average kr/kWh): each minute's energy at the price that applied then."""
    pts = sorted((t, p) for t, p in prices if p is not None)
    total = kwh = 0.0
    i = 0
    for m, w in enumerate(prof):
        t = start + 60 * m + 30
        while i + 1 < len(pts) and pts[i + 1][0] <= t:
            i += 1
        price = pts[i][1] if pts and pts[i][0] <= t else (pts[0][1] if pts else fallback)
        e = w / 60 / 1000
        total += e * price
        kwh += e
    return round(total, 2), round(total / kwh, 3) if kwh else fallback


# --- when will it be done? ---------------------------------------------------------

def distance(a: Sequence[int], b: Sequence[int]) -> float:
    """How differently two cycles have drawn power over the same minutes (mean watt difference)."""
    n = min(len(a), len(b))
    return sum(abs(a[i] - b[i]) for i in range(n)) / n if n else math.inf


def expected(so_far: Sequence[int], known: Sequence[dict]) -> Optional[dict]:
    """Expected length of a running cycle, from earlier cycles on the same machine.

    Only cycles longer than the time already run can match. In the first minutes everything looks alike, so the
    guess is their median; after that it's the cycles whose power curve so far looks most like this one (the same
    program heats, pauses and spins at the same times).
    """
    t = len(so_far)
    cands = [k for k in known if k["minutes"] > t]
    if not cands:
        return None
    if t < 5:
        return {"minutes": round(median(k["minutes"] for k in cands)), "like": None, "distance": None}
    ranked = sorted((distance(so_far, k["profile"][:t]), i, k) for i, k in enumerate(cands))
    best = ranked[0][0]
    # up to three cycles about as close as the best one; a clearly different program doesn't drag the guess
    near = [(d, k) for d, _, k in ranked[:3] if d <= best * 1.3 + 20]
    weights = [1 / (1 + d) for d, _ in near]
    minutes = sum(k["minutes"] * w for (_, k), w in zip(near, weights)) / sum(weights)
    return {"minutes": round(minutes), "like": near[0][1].get("id"), "distance": round(best)}


def accuracy(known: Sequence[dict], at_minute: int = 20) -> Optional[dict]:
    """How far off the guess would have been for each earlier cycle, `at_minute` minutes in (leave one out)."""
    errors = []
    for i, k in enumerate(known):
        if k["minutes"] <= at_minute:
            continue
        guess = expected(k["profile"][:at_minute], known[:i] + known[i + 1:])
        if guess:
            errors.append(abs(guess["minutes"] - k["minutes"]))
    if len(errors) < 3:
        return None
    return {"at_minute": at_minute, "median_error": round(median(errors)), "cycles": len(errors)}

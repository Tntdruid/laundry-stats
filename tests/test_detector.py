"""The cycle detection, on readings shaped like the real washer and dryer (see dev/demo_data.py)."""
import random

import pytest

import demo_data
import detector
from config import DEFAULT_MACHINES, Machine

WASHER = Machine(**DEFAULT_MACHINES[0])
DRYER = Machine(**DEFAULT_MACHINES[1])
T = 1_800_000_000


def scan(machine, readings, now=None, since=None):
    return detector.scan(machine, readings, now or readings[-1][0] + 3600, since or readings[0][0])


@pytest.mark.parametrize("program", list(demo_data.WASH_PROGRAMS))
def test_each_wash_program_is_one_cycle(program):
    pattern = demo_data.WASH_PROGRAMS[program]
    r = scan(WASHER, demo_data.wash(T, pattern, random.Random(1)))
    assert len(r.cycles) == 1
    c = r.cycles[0]
    assert abs(c.start - T) <= 10
    # it ends when the low ticking after the spin starts, not 8 minutes later
    assert abs(c.minutes - len(pattern.rstrip("_"))) <= 1
    assert r.current is None


@pytest.mark.parametrize("minutes", [100, 112])
def test_dryer_anti_crease_bursts_are_not_new_cycles(minutes):
    r = scan(DRYER, demo_data.dry(T, minutes, random.Random(2), crease_minutes=60))
    assert len(r.cycles) == 1
    assert abs(r.cycles[0].minutes - minutes) <= 0.2
    assert r.too_short == 0  # the bursts never even start a cycle


def test_dryer_start_waits_for_a_whole_minute():
    readings = [(T, 0.0), (T + 10, 500.0), (T + 50, 0.0), (T + 600, 0.0)]
    assert scan(DRYER, readings).cycles == []
    assert scan(DRYER, readings).current is None


def test_short_runs_are_not_counted():
    readings = [(T, 0.0), (T + 60, 400.0), (T + 10 * 60, 0.0)]
    r = scan(WASHER, readings)
    assert r.cycles == [] and r.too_short == 1


def test_a_pause_shorter_than_stop_minutes_does_not_split_a_wash():
    readings = [(T, 0.0), (T + 60, 300.0), (T + 20 * 60, 10.0), (T + 23 * 60, 300.0), (T + 50 * 60, 0.0)]
    r = scan(WASHER, readings)
    assert len(r.cycles) == 1
    assert r.cycles[0].minutes == pytest.approx(49)


def test_unavailable_plug_keeps_the_last_value():
    readings = [(T, 0.0), (T + 60, 300.0), (T + 20 * 60, None), (T + 40 * 60, 300.0), (T + 50 * 60, 0.0)]
    r = scan(WASHER, readings)
    assert len(r.cycles) == 1 and r.cycles[0].minutes == pytest.approx(49)


def test_running_cycle_is_reported_and_resume_stays_before_it():
    readings = [(T, 0.0), (T + 60, 0.0), (T + 120, 400.0)]
    r = detector.scan(WASHER, readings, T + 30 * 60, T)
    assert r.cycles == []
    assert r.current.start == T + 120
    assert r.resume <= T + 120


def test_cycle_never_going_quiet_is_dropped():
    readings = [(T, 0.0), (T + 60, 400.0)]
    r = detector.scan(WASHER, readings, T + 13 * 3600, T)
    assert r.cycles == [] and r.current is None and r.abandoned == 1


def test_normal_cycle_after_an_abandoned_one():
    h = 3600
    readings = [(T, 0.0), (T + 60, 400.0), (T + 13 * h, 0.0), (T + 14 * h, 400.0), (T + 15 * h, 0.0)]
    r = detector.scan(WASHER, readings, T + 16 * h, T)
    assert r.abandoned == 1
    assert len(r.cycles) == 1 and r.cycles[0].start == T + 14 * h
    assert r.cycles[0].readings[0] == (T + 14 * h, 400.0)


def test_energy_and_profile():
    run = detector.Run(T, T + 3600, [(T, 1000.0), (T + 1800, 2000.0)])
    s = detector.summarize(run)
    assert s["kwh"] == pytest.approx(1.5)
    assert len(s["profile"]) == 60
    assert s["profile"][0] == 1000 and s["profile"][-1] == 2000
    assert s["heat_minutes"] == 30
    assert s["minutes"] == 60


def test_profile_handles_a_value_change_mid_minute():
    assert detector.profile([(T, 0.0), (T + 30, 100.0)], T, T + 60) == [50]


def test_cost_follows_the_price_over_time():
    prof = [1200] * 60  # 1.2 kW for an hour = 1.2 kWh
    prices = [(T - 100, 1.0), (T + 1800, 3.0)]
    total, avg = detector.cost(prof, T, prices, fallback=9.0)
    assert total == pytest.approx(0.6 * 1.0 + 0.6 * 3.0)
    assert avg == pytest.approx(2.0)
    assert detector.cost(prof, T, [], fallback=2.5) == (3.0, 2.5)


def test_expected_finish_recognises_the_program():
    rnd = random.Random(3)
    known = []
    for i, name in enumerate(["40° kort", "60°", "Bomuld 90°", "40° kort", "60°", "Bomuld 90°"]):
        run = scan(WASHER, demo_data.wash(T + i * 86400, demo_data.WASH_PROGRAMS[name], rnd)).cycles[0]
        known.append({"id": i, **detector.summarize(run)})
    for name in ("60°", "Bomuld 90°", "40° kort"):
        minutes = len(demo_data.WASH_PROGRAMS[name].rstrip("_"))
        run = scan(WASHER, demo_data.wash(T, demo_data.WASH_PROGRAMS[name], rnd)).cycles[0]
        # 35 minutes in: a 60° and a 90° wash both heat for the first half hour, so earlier they look the same
        so_far = detector.summarize(run)["profile"][:35]
        guess = detector.expected(so_far, known)
        assert abs(guess["minutes"] - minutes) <= 3, name


def test_expected_finish_without_history():
    assert detector.expected([100] * 10, []) is None
    assert detector.expected([100] * 2, [{"minutes": 100, "profile": [1] * 100}])["minutes"] == 100

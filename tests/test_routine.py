"""Testar inaktivitetskollen och rutin-inlärningen med påhittade dagar.  Kör:  pytest"""

from datetime import datetime

import numpy as np

import config as cfg
from routine import ActivityMonitor, CheckupSchedule, Routine


def at(hour, minute=0, day=2):
    return datetime(2026, 11, day, hour, minute).timestamp()


def pose(shift=0.0):
    kp = np.tile([0.5, 0.5], (17, 1)) + shift
    return {"kp": kp, "conf": np.ones(17), "hip_y": 0.5, "angle": 5, "aspect": 0.5}


def run(monitor, start, minutes, moving=False, lying=False, step=2):
    """Spelar upp `minutes` minuter, en bild var `step`:e sekund. Returnerar första kollen (eller None)."""
    for i in range(int(minutes * 60 / step)):
        p = pose(0.05 * (i % 2) if moving else 0.0)
        reason = monitor.update(start + i * step, p, lying=lying)
        if reason:
            return reason
    return None


def monitor():
    return ActivityMonitor(Routine(path=None))


# ---- stillhet ----

def test_moving_never_asks():
    assert run(monitor(), at(10), 180, moving=True) is None


def test_still_during_the_day_asks_after_about_two_hours():
    m = monitor()
    assert run(m, at(10), 110) is None
    m2 = monitor()
    assert "Ingen rörelse sedan 10:00" in run(m2, at(10), 130)


def test_lying_still_asks_sooner():
    reason = run(monitor(), at(10), 40, lying=True)
    assert reason and reason.startswith("Ligger stilla")


def test_sleeping_at_night_does_not_ask():
    assert run(monitor(), at(23), 7 * 60, lying=True, step=10) is None


def test_asks_only_once_until_movement():
    m = monitor()
    assert run(m, at(10), 130)
    assert run(m, at(12, 10), 30) is None


def test_ok_answer_counts_as_activity():
    m = monitor()
    run(m, at(10), 130)
    m.mark_active(at(12, 10))
    assert run(m, at(12, 10), 60) is None


def test_small_jitter_is_not_movement():
    m = monitor()
    for i in range(130 * 30):
        p = pose()
        p["kp"] = p["kp"] + np.random.default_rng(i).normal(0, 0.002, (17, 2))
        if m.update(at(10) + i * 2, p):
            break
    assert m.asked


def test_coming_into_view_is_movement():
    m = monitor()
    m.update(at(10), None)
    m.update(at(10, 1), None)
    m.update(at(10, 2), pose())
    assert m.last_motion == at(10, 2)


# ---- rutiner ----

def teach_days(routine, days, active_hours):
    """Låtsas att personen rört sig 15 minuter/timme under active_hours, och varit stilla annars."""
    for d in range(days):
        for h in range(24):
            for minute in range(60):
                routine.tick(at(h, minute, day=1 + d), 60, h in active_hours and minute < 15)
    routine.tick(at(0, 0, day=1 + days), 0, False)       # midnatt -> gårdagen lärs in


def test_learns_daily_walk_and_does_not_ask_then():
    r = Routine(path=None)
    awake_but_out = set(range(7, 22)) - {13, 14, 15}      # ute och går 13–16 varje dag
    teach_days(r, cfg.LEARN_MIN_DAYS, awake_but_out)
    assert r.learned(14) and r.expected_rate(14) < 1 and r.expected_rate(10) > 10
    m = ActivityMonitor(r)
    assert run(m, at(13, day=10), 170) is None            # borta på promenad – ingen koll


def test_not_learned_yet_uses_default_day():
    r = Routine(path=None)
    teach_days(r, cfg.LEARN_MIN_DAYS - 1, set())
    assert not r.learned(10) and r.expected_rate(10) == cfg.DEFAULT_ACTIVE_RATE


def test_saves_and_loads(tmp_path):
    path = str(tmp_path / "rutiner.json")
    r = Routine(path=path)
    teach_days(r, 3, {9})
    r.save()
    assert Routine(path=path).days == r.days


# ---- dagliga koller ----

def test_daily_checkup_once_per_day():
    s = CheckupSchedule("10:00, 16:00")
    assert s.due(at(9, 59)) is None
    assert s.due(at(10, 0)) == "10:00"
    assert s.due(at(10, 5)) is None
    assert s.due(at(16, 1)) == "16:00"
    assert s.due(at(10, 0, day=3)) == "10:00"


def test_daily_checkup_skipped_if_started_late():
    assert CheckupSchedule("10:00").due(at(11)) is None

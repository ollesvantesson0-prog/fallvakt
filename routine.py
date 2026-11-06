"""
Inaktivitetskoll och rutiner: märker om personen varit stilla ovanligt länge, och lär sig hens dygn.

Varje timme på dygnet får ett mått på hur aktiv personen brukar vara då: "rörelseminuter per timme".
När det inte har varit någon rörelse på ett tag räknas det ut hur mycket rörelse som BORDE ha hänt
under den tiden. Har det uteblivit mycket mer än vanligt frågar datorn hur personen mår.

  Mitt på dagen, när hen brukar vara igång  -> frågar efter ca 2 timmar utan rörelse
  Ligger ner och är helt stilla              -> frågar efter ca 30 minuter
  På natten, när hen brukar sova             -> mycket senare
  Brukar hen vara ute 14–16?                 -> det lär den sig, och då frågar den inte där

De första dagarna, innan den har lärt sig, används ett vanligt dygn (vaken 7–22).
Det som sparas (rutiner.json) är bara antal rörelseminuter per timme, inga bilder.
"""

import json
import os
from datetime import datetime, timedelta

import numpy as np

import config as cfg

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rutiner.json")


def default_rate(hour):
    awake = cfg.DEFAULT_AWAKE[0] <= hour < cfg.DEFAULT_AWAKE[1]
    return cfg.DEFAULT_ACTIVE_RATE if awake else cfg.DEFAULT_NIGHT_RATE


def duration_text(seconds):
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h} tim {m} min" if h else f"{m} min"


# =====================================================================
# Rutinerna: hur aktiv personen brukar vara varje timme
# =====================================================================

class Routine:
    def __init__(self, path=PROFILE_PATH):
        self.path = path
        self.rate = [float(default_rate(h)) for h in range(24)]   # inlärda rörelseminuter per timme
        self.days = [0] * 24                    # hur många dagar varje timme har lärts in
        self.day = None                         # dagens datum
        self.moved = [0] * 24                   # rörelseminuter idag
        self.watched = [0.0] * 24               # sekunder idag som kameran var igång
        self._load()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.rate, self.days = d["rate"], d["days"]
            self.day, self.moved, self.watched = d["day"], d["moved"], d["watched"]
        except Exception as e:
            print(f"  !! Kunde inte läsa {self.path} ({e}) – börjar om med ett vanligt dygn")

    def save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w") as f:
                json.dump({"rate": self.rate, "days": self.days, "day": self.day,
                           "moved": self.moved, "watched": self.watched}, f)
        except Exception as e:
            print(f"  !! Kunde inte spara rutinerna: {e}")

    def learned(self, hour):
        return self.days[hour] >= cfg.LEARN_MIN_DAYS

    def expected_rate(self, hour):
        return self.rate[hour] if self.learned(hour) else default_rate(hour)

    def tick(self, t, dt, moved_new_minute):
        """Räknar dagens aktivitet. Vid midnatt lärs gårdagen in."""
        now = datetime.fromtimestamp(t)
        day = now.date().isoformat()
        if self.day != day:
            if self.day is not None:
                self._learn_day()
            self.day, self.moved, self.watched = day, [0] * 24, [0.0] * 24
        self.watched[now.hour] += dt
        if moved_new_minute:
            self.moved[now.hour] += 1

    def _learn_day(self):
        for h in range(24):
            if self.watched[h] < cfg.LEARN_MIN_WATCHED:
                continue                        # kameran var inte igång tillräckligt – vet inget
            observed = self.moved[h] * 3600 / self.watched[h]
            self.days[h] += 1
            n = min(self.days[h], cfg.LEARN_DAYS)   # medel av de senaste ~2 veckorna
            self.rate[h] += (observed - self.rate[h]) / n

    def expected_moves(self, t0, t1):
        """Hur många rörelseminuter brukar det bli mellan t0 och t1?"""
        total, t = 0.0, t0
        while t < t1:
            now = datetime.fromtimestamp(t)
            next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
            end = min(next_hour, t1)
            total += self.expected_rate(now.hour) * (end - t) / 3600
            t = end
        return total


# =====================================================================
# Rörelse och inaktivitet
# =====================================================================

class ActivityMonitor:
    def __init__(self, routine=None):
        self.routine = routine if routine is not None else Routine()
        self.last_motion = None
        self.last_t = None
        self.last_save = 0.0
        self.ref = None                 # (tid, kroppspunkter, vilka som syns) att jämföra med
        self.unseen_since = None
        self.last_moved_minute = None
        self.asked = False              # har redan frågat – frågar inte igen förrän personen rört sig

    def update(self, t, pose, lying=False, may_ask=True):
        """En gång per bild. Returnerar en text om varför det är dags för en koll, annars None."""
        if self.last_motion is None:
            self.last_motion = t
        dt = min(t - self.last_t, 1.0) if self.last_t else 0.0
        self.last_t = t

        new_minute = False
        if self._moved(t, pose):
            self.last_motion, self.asked = t, False
            minute = int(t // 60)
            new_minute = minute != self.last_moved_minute
            self.last_moved_minute = minute
        self.routine.tick(t, dt, new_minute)

        if t - self.last_save >= 300:
            self.last_save = t
            self.routine.save()

        if self.asked or not may_ask:
            return None
        return self._check(t, pose, lying)

    def resume(self, t):
        """Kameran har varit av – vi vet inget om tiden som gått, så börja räkna om."""
        self.last_motion, self.ref, self.unseen_since, self.asked = t, None, None, False
        self.last_t = None

    def mark_active(self, t):
        """Personen svarade att allt är bra – räkna det som aktivitet."""
        self.last_motion, self.asked = t, False

    def still_seconds(self, t):
        return t - self.last_motion if self.last_motion else 0.0

    def _moved(self, t, pose):
        if pose is None:
            self.unseen_since = self.unseen_since or t
            self.ref = None
            return False
        # Kommer in i bild efter att ha varit borta en stund = rörelse
        appeared = self.unseen_since is not None and t - self.unseen_since >= 2
        self.unseen_since = None

        ok = pose["conf"] > cfg.MIN_KP_CONF
        if self.ref is None:
            self.ref = (t, pose["kp"], ok)
            return appeared
        ref_t, ref_kp, ref_ok = self.ref
        if t - ref_t < cfg.MOVE_INTERVAL:
            return appeared
        self.ref = (t, pose["kp"], ok)
        both = ok & ref_ok
        if both.sum() < 2:
            return appeared
        dist = np.sort(np.linalg.norm(pose["kp"][both] - ref_kp[both], axis=1))
        # Näst största flytten: en enstaka punkt som "hoppar" är brus, men armbåge + handled räcker
        return appeared or float(dist[-2]) >= cfg.MOVE_THRESHOLD

    def _check(self, t, pose, lying):
        still = t - self.last_motion
        if still < cfg.INACTIVITY_MIN_MINUTES * 60:
            return None
        lying = pose is not None and lying
        expected = self.routine.expected_moves(self.last_motion, t)
        limit = cfg.LYING_STILL_LIMIT if lying else cfg.INACTIVITY_LIMIT
        if expected < limit and still < cfg.INACTIVITY_MAX_HOURS * 3600:
            return None
        self.asked = True
        since = datetime.fromtimestamp(self.last_motion).strftime("%H:%M")
        what = "Ligger stilla" if lying else "Ingen rörelse" + (" i bild" if pose is None else "")
        return f"{what} sedan {since} ({duration_text(still)}), ovanligt länge för den här tiden."


# =====================================================================
# Dagliga koller
# =====================================================================

class CheckupSchedule:
    """Säger till när det är dags för en daglig koll (CHECKUP_TIMES, t.ex. "10:00,16:00")."""

    def __init__(self, times=None):
        times = cfg.CHECKUP_TIMES if times is None else times
        self.times = [s.strip() for s in times.split(",") if s.strip()]
        self.done = set()               # (datum, tid) som redan körts

    def due(self, t):
        now = datetime.fromtimestamp(t)
        for hhmm in self.times:
            h, m = map(int, hhmm.split(":"))
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            key = (now.date(), hhmm)
            # Inom en kvart efter utsatt tid (startar programmet senare hoppas kollen över)
            if key not in self.done and at <= now < at + timedelta(minutes=15):
                self.done.add(key)
                return hhmm
        return None


def print_routine(routine=None):
    """Visar vad Fallvakt har lärt sig:  python main.py --rutiner"""
    r = routine or Routine()
    rates = [r.expected_rate(h) for h in range(24)]
    scale = 30 / max(max(rates), 1)
    print("Personens dygn (rörelseminuter per timme) och när en koll görs utan rörelse:\n")
    for h, rate in enumerate(rates):
        hours = min(cfg.INACTIVITY_LIMIT / rate if rate > 0 else 1e9, cfg.INACTIVITY_MAX_HOURS)
        after = "~" + duration_text(max(hours * 3600, cfg.INACTIVITY_MIN_MINUTES * 60))
        source = f"inlärt, {r.days[h]} dagar" if r.learned(h) else "standard"
        print(f"  {h:02d}  {'█' * round(rate * scale):30s} {rate:5.1f}   koll efter {after:16s} ({source})")

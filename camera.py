"""
När kameran får vara på – för den som inte vill ha en kamera igång hela tiden.

Tre lägen (CAMERA_MODE i .env):
  alltid         kameran är alltid på (som förut)
  tider          bara vissa tider, t.ex. CAMERA_HOURS=22-08
  vid_misstanke  av, men startar några minuter när något verkar fel:
                 en smäll, ett rop på hjälp eller inget svar på dagens koll

I alla lägen kan personen säga "pausa kameran" / "slå på kameran", och anhöriga kan skriva /paus och /på
i Telegram. Pågår ett larm eller en röstkoll stängs kameran aldrig av mitt i.
Lampan bredvid Mac-kameran lyser när den är på – så personen ser alltid själv när den tittar.
"""

from datetime import datetime

import config as cfg

MODES = ("alltid", "tider", "vid_misstanke")


def parse_hours(text):
    """ "22-08,13:30-15" -> [(1320, 480), (810, 900)]  (minuter efter midnatt)"""
    def minutes(s):
        h, _, m = s.strip().partition(":")
        return int(h) * 60 + int(m or 0)
    windows = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            windows.append((minutes(a), minutes(b)))
    return windows


def in_windows(windows, t):
    now = datetime.fromtimestamp(t)
    m = now.hour * 60 + now.minute
    return any((a <= m < b) if a <= b else (m >= a or m < b) for a, b in windows)   # 22-08 går över midnatt


def clock(t):
    return datetime.fromtimestamp(t).strftime("%H:%M")


class CameraGate:
    def __init__(self, mode=None, hours=None):
        self.mode = (mode or cfg.CAMERA_MODE).strip().lower()
        if self.mode not in MODES:
            print(f"OBS: okänt CAMERA_MODE '{self.mode}' – använder 'alltid' (välj {', '.join(MODES)})")
            self.mode = "alltid"
        self.windows = parse_hours(cfg.CAMERA_HOURS if hours is None else hours)
        self.paused_until = 0.0         # personen eller en anhörig har pausat
        self.on_until = 0.0             # någon har slagit på kameran
        self.awake_until = 0.0          # väckt av en misstanke
        self.wake_reason = ""
        self.ask_if_unseen = False      # fråga med rösten om ingen syntes medan kameran var väckt
        self.seen_while_awake = False

    # ---- ändras av röst, Telegram och misstankar ----

    def pause(self, t, hours=None):
        self.paused_until = t + (hours or cfg.MANUAL_HOURS) * 3600
        self.on_until = 0.0

    def turn_on(self, t, hours=None):
        self.paused_until = 0.0
        if self.mode != "alltid":
            self.on_until = t + (hours or cfg.MANUAL_HOURS) * 3600

    def paused(self, t):
        return t < self.paused_until

    def wake(self, t, reason, ask_if_unseen=False):
        """Något verkar fel – starta kameran en stund. Returnerar False om den redan var på."""
        if self._normally_on(t):
            return False
        self.awake_until = t + cfg.WAKE_MINUTES * 60
        self.wake_reason, self.ask_if_unseen, self.seen_while_awake = reason, ask_if_unseen, False
        return True

    def note_seen(self):
        self.seen_while_awake = True

    def unseen_wake_ended(self, t):
        """Kameran väcktes, ingen syntes och tiden är slut -> anledningen (en gång), annars None."""
        if self.ask_if_unseen and self.awake_until and t >= self.awake_until and not self.seen_while_awake:
            self.ask_if_unseen = False
            return self.wake_reason
        return None

    # ---- frågas varje varv i huvudloopen ----

    def should_watch(self, t, busy=False):
        if busy:
            return True                 # larm eller koll pågår – aldrig av mitt i
        if t < self.awake_until:
            return True
        return self._normally_on(t)

    def _normally_on(self, t):
        if self.paused(t):
            return False
        if t < self.on_until:
            return True
        if self.mode == "alltid":
            return True
        if self.mode == "tider":
            return in_windows(self.windows, t)
        return False

    def status(self, t):
        if t < self.awake_until and not self._normally_on(t):
            return f"Kameran är PÅ till {clock(self.awake_until)} ({self.wake_reason})"
        if self.paused(t):
            return f"Kameran är PAUSAD till {clock(self.paused_until)}"
        if t < self.on_until:
            return f"Kameran är PÅ till {clock(self.on_until)} (påslagen)"
        if self.mode == "alltid":
            return "Kameran är PÅ (alltid)"
        hours = ", ".join(f"{a // 60:02d}:{a % 60:02d}–{b // 60:02d}:{b % 60:02d}" for a, b in self.windows)
        if self.mode == "tider":
            return f"Kameran är {'PÅ' if self._normally_on(t) else 'AV'} (på {hours})"
        return "Kameran är AV (startar vid misstanke)"

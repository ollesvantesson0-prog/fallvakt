"""
Fall-detektering: från kamerans AI-output till "har personen ramlat?".

Två delar:
  1. extract_pose() – gör om AI-modellens kroppspunkter till några enkla mått
  2. FallDetector   – en tillståndsmaskin som avgör vad som händer över tid
"""

import math
from collections import deque

import numpy as np

import config as cfg

# Kroppspunkter i modellen (COCO-formatet, 17 punkter)
NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 0, 5, 6, 11, 12
SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


# =====================================================================
# 1. Kroppspunkter -> enkla mått
# =====================================================================

def extract_pose(result):
    """Plockar ut den största personen i bilden och räknar fram:
       hip_y  – höftens höjd (0 = överkant, 1 = nederkant av bilden)
       angle  – överkroppens lutning i grader (0 = rak upp, 90 = ligger ner)
       aspect – bredd/höjd på personens ruta
    Returnerar None om ingen person syns."""
    if result.keypoints is None or result.boxes is None or len(result.boxes) == 0:
        return None

    boxes = result.boxes.xyxyn.cpu().numpy()          # rutor, 0–1
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    i = int(np.argmax(areas))                          # största personen = närmast kameran

    kp = result.keypoints.xyn[i].cpu().numpy()        # (17, 2) punkter, 0–1
    kp_px = result.keypoints.xy[i].cpu().numpy()      # samma punkter i pixlar
    conf = result.keypoints.conf
    conf = conf[i].cpu().numpy() if conf is not None else np.ones(17)

    # Bredd/höjd och vinkel räknas i PIXLAR – annars blir de fel eftersom bilden är bredare än hög
    px1, py1, px2, py2 = result.boxes.xyxy[i].cpu().numpy()
    aspect = (px2 - px1) / max(py2 - py1, 1e-6)

    ok = lambda j: conf[j] > cfg.MIN_KP_CONF
    hips = [kp[j] for j in (L_HIP, R_HIP) if ok(j)]
    hips_px = [kp_px[j] for j in (L_HIP, R_HIP) if ok(j)]
    shoulders_px = [kp_px[j] for j in (L_SHOULDER, R_SHOULDER) if ok(j)]

    _, y1, _, y2 = boxes[i]
    hip_y = float(np.mean([h[1] for h in hips])) if hips else float((y1 + y2) / 2)

    angle = None
    if hips_px and shoulders_px:
        hx, hy = np.mean(hips_px, axis=0)
        sx, sy = np.mean(shoulders_px, axis=0)
        angle = math.degrees(math.atan2(abs(sx - hx), abs(hy - sy) + 1e-6))   # 0 = lodrätt

    return {"hip_y": hip_y, "angle": angle, "aspect": float(aspect), "kp": kp, "conf": conf}


def is_lying(pose):
    """Räcker att EN kontroll säger "ligger": lutande överkropp ELLER bred, låg kroppsruta."""
    by_angle = pose["angle"] is not None and pose["angle"] >= cfg.LYING_ANGLE
    return by_angle or pose["aspect"] >= cfg.LYING_ASPECT


def is_upright(pose):
    """Båda måste säga "upprätt" (med marginal så att det inte fladdrar mellan lägena)."""
    angle_ok = pose["angle"] is None or pose["angle"] <= cfg.LYING_ANGLE - 20
    return angle_ok and pose["aspect"] <= cfg.LYING_ASPECT - 0.4


# =====================================================================
# 2. Tillståndsmaskinen
#
#    OK -> MÖJLIGT FALL -> LIGGER KVAR -> FRÅGAR ("Hur mår du?")
#                                           |-- mår bra        -> SVARADE OK (frågar igen om hen ligger kvar länge)
#                                           |-- behöver hjälp  -> LARM
#                                           '-- tyst (2 ggr)   -> LARM
#    Reser sig personen innan larm -> OK.   Reser sig efter larm -> "RESTE SIG" -> OK
#    Utan röstkoll: LIGGER KVAR i 10 s -> LARM
#    Ropar personen på hjälp (när som helst) -> LARM
# =====================================================================

class FallDetector:
    def __init__(self, use_voice=False):
        self.use_voice = use_voice
        self.state = "OK"
        self.speed = 0.0
        self.hip_history = deque()      # (tid, hip_y)
        self.drop_time = None
        self.down_since = None
        self.upright_since = None
        self.last_alarm = -1e9
        self.alarm_reason = ""
        # röstkollen
        self.ask_id = 0                 # varje fråga får ett nummer, så att gamla svar kan ignoreras
        self.ask_attempt = 0
        self.ask_started = None
        self.voice_result = None        # (ask_id, resultat, sammanfattning) – sätts av röst-tråden
        self.ok_since = None
        self.help_call = None           # sätts av lyssnaren när någon ropar på hjälp
        self.alarm_by_call = False

    # ---- anropas utifrån ----

    def update(self, t, pose):
        """Anropas en gång per bild. Returnerar None, "FRÅGA", "LARM" eller "RESTE SIG"."""
        if pose is None:
            # Ingen person syns. Föll hen precis snabbt har hen troligen hamnat på golvet utanför bild.
            self.hip_history.clear()
            if self.state == "MÖJLIGT FALL":
                self._go_down(t)
            return self._timers(t)

        self.speed = self._hip_speed(t, pose["hip_y"])
        lying, upright = is_lying(pose), is_upright(pose)

        if self.state == "OK" and self.speed >= cfg.DROP_SPEED:
            self.state, self.drop_time = "MÖJLIGT FALL", t

        if self.state == "MÖJLIGT FALL":
            if lying:
                self._go_down(t)
            elif t - self.drop_time > cfg.DROP_TO_LYING_WINDOW:
                self.state = "OK"           # satte sig bara snabbt, eller böjde sig ner

        elif self.state in ("LIGGER KVAR", "FRÅGAR"):
            if upright:
                self._reset()               # reste sig själv – inget larm

        elif self.state in ("LARM", "SVARADE OK"):
            if upright:
                self.upright_since = self.upright_since or t
                if t - self.upright_since >= cfg.UPRIGHT_RESET_SECONDS:
                    # Ropade personen på hjälp stående är "har rest sig" inget besked – återställ tyst
                    was_alarm = self.state == "LARM" and not self.alarm_by_call
                    self._reset()
                    if was_alarm:
                        return "RESTE SIG"
            else:
                self.upright_since = None

        return self._timers(t)

    def give_voice_result(self, ask_id, result, summary):
        """Anropas från röst-tråden när samtalet är klart."""
        self.voice_result = (ask_id, result, summary)

    def call_for_help(self, summary):
        """Anropas från lyssnaren när någon ropat på hjälp och inte sagt nej på kontrollfrågan."""
        self.help_call = summary

    def cancel_alarm(self):
        """Anhörig tryckte på "Falsklarm"."""
        self._reset()

    def seconds_down(self, t):
        if self.state in ("LIGGER KVAR", "FRÅGAR", "LARM", "SVARADE OK") and self.down_since:
            return t - self.down_since
        return 0

    # ---- intern logik ----

    def _hip_speed(self, t, hip_y):
        self.hip_history.append((t, hip_y))
        while t - self.hip_history[0][0] > cfg.SPEED_WINDOW:
            self.hip_history.popleft()
        t0, y0 = self.hip_history[0]
        if t - t0 < 0.15:
            return 0.0
        return (hip_y - y0) / (t - t0)      # positivt = nedåt i bilden

    def _go_down(self, t):
        self.state, self.down_since, self.ask_attempt = "LIGGER KVAR", t, 0

    def _reset(self):
        self.state, self.upright_since, self.voice_result = "OK", None, None
        self.alarm_by_call = False
        self.ask_attempt = 0
        self.ask_id += 1                # ett sent svar från en pågående fråga ignoreras

    def _ask(self, t):
        self.state, self.ask_started, self.voice_result = "FRÅGAR", t, None
        self.ask_id += 1
        self.ask_attempt += 1
        return "FRÅGA"

    def _alarm(self, t, reason, by_call=False):
        self.state, self.alarm_reason, self.alarm_by_call = "LARM", reason, by_call
        if t - self.last_alarm < cfg.ALARM_COOLDOWN:
            return None                 # larmade nyss – skicka inte igen
        self.last_alarm = t
        return "LARM"

    def _timers(self, t):
        """Allt som händer för att TID har gått."""
        if self.help_call:
            summary, self.help_call = self.help_call, None
            if self.state != "LARM":
                return self._alarm(t, f"Personen ropade på hjälp. {summary}", by_call=True)

        if self.state == "LIGGER KVAR":
            down = t - self.down_since
            if self.use_voice and down >= cfg.ASK_AFTER_SECONDS:
                return self._ask(t)
            if not self.use_voice and down >= cfg.STILL_DOWN_SECONDS:
                return self._alarm(t, f"Personen har legat ner i {cfg.STILL_DOWN_SECONDS} sekunder.")

        elif self.state == "FRÅGAR":
            vr = self.voice_result
            if vr and vr[0] == self.ask_id:
                self.voice_result = None
                _, result, summary = vr
                if result == "ok":
                    self.state, self.ok_since = "SVARADE OK", t
                    return None
                if result == "hjälp":
                    return self._alarm(t, f"Personen behöver hjälp. {summary}")
                if self.ask_attempt < cfg.VOICE_ATTEMPTS:
                    return self._ask(t)          # tyst – fråga en gång till
                return self._alarm(t, "Personen svarar inte efter fallet.")
            if t - self.ask_started > cfg.VOICE_TIMEOUT:
                return self._alarm(t, "Röstkollen blev inte klar (timeout).")

        elif self.state == "SVARADE OK":
            if t - self.ok_since >= cfg.RECHECK_AFTER:
                self.ask_attempt = 0
                return self._ask(t)              # ligger fortfarande kvar – dubbelkolla

        return None

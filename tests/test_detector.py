"""Testar fall-logiken med påhittade rörelser – ingen kamera behövs.  Kör:  pytest"""

from detector import FallDetector

FPS = 20


def P(hip_y, angle):
    """En påhittad kroppsställning."""
    return {"hip_y": hip_y, "angle": angle, "aspect": 0.5}


STAND = [P(0.5, 5)] * 40
FALL = [P(0.5 + 0.35 * k / 8, 5 + 80 * k / 8) for k in range(9)]     # snabbt ner på ~0.4 s
LIE = P(0.85, 85)
UP = P(0.5, 5)


def run(frames, use_voice=False, voice_answers=(), answer_delay=12):
    """Spelar upp bilder och returnerar (händelser, detektorn). voice_answers = svar på varje fråga."""
    d = FallDetector(use_voice=use_voice)
    answers, pending, events = list(voice_answers), None, []
    for i, pose in enumerate(frames):
        t = i / FPS
        if pending and t >= pending[0]:
            d.give_voice_result(pending[1], *pending[2])
            pending = None
        ev = d.update(t, pose)
        if ev:
            events.append(ev)
            if ev == "FRÅGA":
                ans = answers.pop(0) if answers else ("inget", "")
                pending = (t + answer_delay, d.ask_id, ans)
    return events, d


def seconds(n, pose):
    return [pose] * int(n * FPS)


# ---- utan röstkoll ----

def test_fall_and_stay_down_alarms():
    events, d = run(STAND + FALL + seconds(15, LIE))
    assert events == ["LARM"]


def test_fall_and_get_up_quickly_no_alarm():
    events, d = run(STAND + FALL + seconds(5, LIE) + seconds(5, UP))
    assert events == [] and d.state == "OK"


def test_sitting_down_fast_no_alarm():
    sit = [P(0.5 + 0.2 * k / 6, 10) for k in range(7)]
    events, _ = run(STAND + sit + seconds(15, P(0.7, 10)))
    assert events == []


def test_lying_down_slowly_no_alarm():
    slow = [P(0.5 + 0.3 * k / 200, 5 + 80 * k / 200) for k in range(201)]
    events, _ = run(STAND + slow + seconds(15, P(0.8, 85)))
    assert events == []


def test_fall_out_of_frame_alarms():
    out = [P(0.5 + 0.3 * k / 6, 10) for k in range(7)]
    events, _ = run(STAND + out + seconds(15, None))
    assert events == ["LARM"]


def test_get_up_after_alarm_reports_it():
    events, d = run(STAND + FALL + seconds(15, LIE) + seconds(5, UP))
    assert events == ["LARM", "RESTE SIG"] and d.state == "OK"


# ---- med röstkoll ----

def test_says_ok_no_alarm():
    events, d = run(STAND + FALL + seconds(30, LIE), use_voice=True, voice_answers=[("ok", "mår bra")])
    assert events == ["FRÅGA"] and d.state == "SVARADE OK"


def test_asks_for_help_alarms():
    events, d = run(STAND + FALL + seconds(30, LIE), use_voice=True, voice_answers=[("hjälp", "ont i foten")])
    assert events == ["FRÅGA", "LARM"] and "ont i foten" in d.alarm_reason


def test_silent_twice_alarms():
    events, _ = run(STAND + FALL + seconds(40, LIE), use_voice=True)
    assert events == ["FRÅGA", "FRÅGA", "LARM"]


def test_says_ok_but_stays_down_asks_again():
    events, _ = run(STAND + FALL + seconds(160, LIE), use_voice=True, voice_answers=[("ok", "okej")])
    assert events[:2] == ["FRÅGA", "FRÅGA"]


def test_gets_up_during_question_cancels():
    events, d = run(STAND + FALL + seconds(8, LIE) + seconds(10, UP), use_voice=True,
                    voice_answers=[("hjälp", "ja")])
    assert "LARM" not in events and d.state == "OK"


def test_false_alarm_button_resets():
    events, d = run(STAND + FALL + seconds(15, LIE))
    d.cancel_alarm()
    assert d.state == "OK"

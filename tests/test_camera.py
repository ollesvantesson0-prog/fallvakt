"""Testar när kameran får vara på, smäll-detektering och paus med röst/Telegram.  Kör:  pytest"""

from datetime import datetime

import numpy as np
import pytest

import config as cfg
from brain import camera_command
from camera import CameraGate, parse_hours
from detector import FallDetector
from notify import handle_command
from voice import is_thud


def at(hour, minute=0):
    return datetime(2026, 11, 2, hour, minute).timestamp()


# ---- lägen ----

def test_always_mode_is_on():
    assert CameraGate("alltid").should_watch(at(12))


def test_hours_mode_over_midnight():
    g = CameraGate("tider", "22-08")
    assert g.should_watch(at(23)) and g.should_watch(at(3)) and not g.should_watch(at(12))


def test_parse_hours_with_minutes():
    assert parse_hours("22-08, 13:30-15") == [(1320, 480), (810, 900)]


def test_suspicion_mode_is_off_until_woken():
    g = CameraGate("vid_misstanke")
    assert not g.should_watch(at(12))
    assert g.wake(at(12), "hörde en smäll")
    assert g.should_watch(at(12, 2))
    assert not g.should_watch(at(12) + cfg.WAKE_MINUTES * 60 + 1)


def test_wake_does_nothing_when_already_on():
    assert CameraGate("alltid").wake(at(12), "smäll") is False


def test_never_turns_off_during_alarm():
    g = CameraGate("vid_misstanke")
    assert g.should_watch(at(12), busy=True)


# ---- paus ----

def test_pause_turns_off_always_mode_for_a_while():
    g = CameraGate("alltid")
    g.pause(at(12))
    assert not g.should_watch(at(13))
    assert g.should_watch(at(12) + cfg.MANUAL_HOURS * 3600 + 1)


def test_paused_camera_is_not_woken_by_thud():
    g = CameraGate("alltid")
    g.pause(at(12))
    assert g.paused(at(12, 30))      # main.py frågar med rösten i stället för att starta kameran


def test_turn_on_in_suspicion_mode():
    g = CameraGate("vid_misstanke")
    g.turn_on(at(12))
    assert g.should_watch(at(13)) and not g.should_watch(at(12) + cfg.MANUAL_HOURS * 3600 + 1)


def test_unseen_wake_asks_once():
    g = CameraGate("vid_misstanke")
    g.wake(at(12), "hörde en smäll", ask_if_unseen=True)
    end = at(12) + cfg.WAKE_MINUTES * 60
    assert g.unseen_wake_ended(end - 1) is None
    assert g.unseen_wake_ended(end) == "hörde en smäll"
    assert g.unseen_wake_ended(end + 1) is None


def test_seen_wake_does_not_ask():
    g = CameraGate("vid_misstanke")
    g.wake(at(12), "hörde en smäll", ask_if_unseen=True)
    g.note_seen()
    assert g.unseen_wake_ended(at(13)) is None


# ---- kameran startar och personen ligger redan ner ----

LIE = {"hip_y": 0.85, "angle": 85, "aspect": 0.5}


def test_lying_when_woken_counts_as_fall():
    d = FallDetector(use_voice=True)
    d.suspect(100)
    d.update(10, LIE)
    assert d.state == "LIGGER KVAR"


def test_lying_without_suspicion_is_ignored():
    d = FallDetector(use_voice=True)
    d.update(10, LIE)
    assert d.state == "OK"


# ---- röst och ljud ----

@pytest.mark.parametrize("heard, expected", [
    ("Pausa kameran är du snäll", "paus"),
    ("Kan du stänga av kameran?", "paus"),
    ("Fallvakt paus", "paus"),
    ("Slå på kameran igen", "på"),
    ("Vad blir det för väder?", None),
])
def test_camera_command(heard, expected):
    assert camera_command(heard) == expected


def test_thud_is_detected():
    audio = np.random.default_rng(0).normal(0, 0.005, 16000 * 4).astype("float32")
    audio[32000:32800] = 0.6
    assert is_thud(audio)


def test_loud_talking_is_not_a_thud():
    rng = np.random.default_rng(0)
    assert not is_thud((rng.normal(0, 0.15, 16000 * 4)).astype("float32"))
    assert not is_thud(np.zeros(16000 * 4, "float32"))


# ---- Telegram ----

class FakeChat:
    def __init__(self):
        self.replies = []

    def reply(self, text):
        self.replies.append(text)


class FakeVoice:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def test_telegram_pause_is_said_out_loud():
    g, chat, voice = CameraGate("alltid"), FakeChat(), FakeVoice()
    handle_command("/paus 3", voice, g, chat)
    assert "PAUSAD" in chat.replies[0] and "pausat kameran i 3 timmar" in voice.said[0]
    handle_command("/på", voice, g, chat)
    assert "PÅ" in chat.replies[1] and "slagit på kameran" in voice.said[1]


def test_telegram_unknown_command_shows_help():
    chat = FakeChat()
    handle_command("/hej", None, CameraGate("alltid"), chat)
    assert "/paus" in chat.replies[0]

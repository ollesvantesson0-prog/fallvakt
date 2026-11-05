"""Testar att samtal och Telegram-svar gör rätt sak – utan att skicka något på riktigt.  Kör:  pytest"""

import threading

import config as cfg
import notify
from detector import FallDetector


class Recorder:
    def __init__(self):
        self.said, self.replies = [], []

    def say(self, text):
        self.said.append(text)

    def reply(self, text):
        self.replies.append(text)


def test_button_coming_is_read_aloud():
    r = Recorder()
    notify.handle_relative_message("knapp", "kommer", r, None, r)
    assert "på väg" in r.said[0]


def test_text_message_is_read_aloud():
    r = Recorder()
    notify.handle_relative_message("text", "Jag är där om 10 min", r, None, r)
    assert r.said[0].endswith("Jag är där om 10 min")


def test_false_alarm_button_resets_detector():
    r, d = Recorder(), FallDetector()
    d.state = "LARM"
    notify.handle_relative_message("knapp", "falsk", r, d, r)
    assert d.state == "OK"


def test_twilio_call_sends_swedish_message(monkeypatch):
    sent, done = {}, threading.Event()

    class Ok:
        ok = True

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        done.set()
        return Ok()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setattr(cfg, "TWILIO_SID", "AC123")
    monkeypatch.setattr(cfg, "TWILIO_TOKEN", "tok")
    monkeypatch.setattr(cfg, "TWILIO_FROM", "+1555")
    monkeypatch.setattr(cfg, "CALL_TO", "+46700000000")

    notify.call_phone("Ont i höften & kan inte resa sig")
    assert done.wait(2)
    assert sent["data"]["To"] == "+46700000000"
    assert 'language="sv-SE"' in sent["data"]["Twiml"]
    assert "&amp;" in sent["data"]["Twiml"]          # specialtecken måste kodas


def test_no_call_without_twilio(monkeypatch):
    monkeypatch.setattr(cfg, "TWILIO_SID", "")
    called = []
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: called.append(1))
    notify.call_phone("test")
    assert called == []

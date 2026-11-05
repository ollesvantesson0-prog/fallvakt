"""Testar tolkningen av svar och röstsamtalet med påhittat tal och påhittad AI.  Kör:  pytest"""

import threading

import pytest

from brain import Brain, classify_answer
from voice import VoiceCheck


# ---- ordlistan ----

@pytest.mark.parametrize("said, expected", [
    ("Nej, det är okej", "ok"),
    ("nej jag mår bra", "ok"),
    ("jag klarar mig", "ok"),
    ("Ja!", "hjälp"),
    ("hjälp", "hjälp"),
    ("Nej, jag kan inte resa mig", "hjälp"),     # hjälp vinner över nej
    ("Jag har ont i höften", "hjälp"),
    ("", "inget"),
    ("Tack för att du tittade!", "inget"),       # Whisper-hallucination
    ("öh vad", "inget"),
])
def test_wordlist(said, expected):
    assert classify_answer(said) == expected


# ---- påhittad AI och påhittat tal ----

class FakeBrain(Brain):
    def __init__(self, replies):
        self.kind = "claude"
        self.replies = list(replies)

    def _chat(self, system, user):
        return self.replies.pop(0)


class FakeVoice(VoiceCheck):
    def __init__(self, heard, brain):
        self.heard, self.brain, self.said = list(heard), brain, []
        self.speak_lock = threading.Lock()

    def say(self, text):
        self.said.append(text)

    def listen(self):
        return None

    def transcribe(self, audio):
        return self.heard.pop(0) if self.heard else ""


def converse(heard, ai_replies):
    return FakeVoice(heard, FakeBrain(ai_replies)).converse(1)


def test_ai_says_ok():
    res, summary, _ = converse(["Nej då, jag tappade bara en sak"],
                               ['{"beslut":"ok","säg":"Vad skönt.","sammanfattning":"Tappade en sak."}'])
    assert res == "ok"


def test_ai_says_help_even_with_markdown_around_json():
    res, summary, _ = converse(["Aj, jag har brutit handleden"],
                               ['```json\n{"beslut":"hjälp","säg":"Jag larmar.","sammanfattning":"Bruten handled."}\n```'])
    assert res == "hjälp" and summary == "Bruten handled."


def test_ai_follow_up_question():
    res, _, _ = converse(["öh", "jag kommer inte upp"],
                         ['{"beslut":"fråga","säg":"Kan du resa dig?","sammanfattning":"?"}',
                          '{"beslut":"hjälp","säg":"Jag larmar.","sammanfattning":"Kan inte resa sig."}'])
    assert res == "hjälp"


def test_unclear_three_times_alarms_to_be_safe():
    res, _, _ = converse(["hmm", "eh", "vadå"], ['{"beslut":"fråga","säg":"Mår du bra?","sammanfattning":"?"}'] * 3)
    assert res == "hjälp"


def test_broken_ai_falls_back_to_wordlist():
    res, _, _ = converse(["ja hjälp"], ["jag vet inte vad JSON är"])
    assert res == "hjälp"


def test_silence():
    res, _, _ = converse([], [])
    assert res == "inget"

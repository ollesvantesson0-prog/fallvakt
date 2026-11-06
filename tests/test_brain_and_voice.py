"""Testar tolkningen av svar och röstsamtalet med påhittat tal och påhittad AI.  Kör:  pytest"""

import pytest

from brain import Brain, classify_answer, is_call_for_help
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


# ---- rop på hjälp (lyssnaren som är igång hela tiden) ----

@pytest.mark.parametrize("heard, expected", [
    ("Hjälp!", True),
    ("Kan någon hjälpa mig?", True),
    ("Ring ambulans", True),
    ("Jag har ramlat", True),
    ("Ring 112", True),
    ("Ja", False),                               # "ja" räcker inte när ingen har frågat
    ("Det gör ont i ryggen idag", False),
    ("Vad blir det till middag?", False),
    ("Tack för att du tittade!", False),
])
def test_call_for_help(heard, expected):
    assert is_call_for_help(heard) == expected


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
        self._init_sync()

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


def handle_call(heard, alarms):
    v = FakeVoice(heard, FakeBrain([]))
    v.brain.kind = "ordlista"
    v.handle_call("hjälp", on_help=alarms.append)
    return v


def test_call_for_help_says_no_no_alarm():
    alarms = []
    handle_call(["nej, det var inget"], alarms)
    assert alarms == []


def test_call_for_help_yes_alarms():
    alarms = []
    handle_call(["ja"], alarms)
    assert len(alarms) == 1 and "hjälp" in alarms[0]


def test_call_for_help_silence_alarms():
    alarms = []
    v = handle_call([], alarms)
    assert len(alarms) == 1 and v.busy_count == 0


# ---- koller (inaktivitet / daglig koll) ----

def check_up(heard, ai_replies):
    results = []
    v = FakeVoice(heard, FakeBrain(ai_replies))
    v.check_up("Hur mår du?", "Daglig koll.", lambda res, summary: results.append(res))
    return results, v


def test_check_up_ok():
    results, v = check_up(["Jodå, jag läser bara"],
                          ['{"beslut":"ok","säg":"Vad bra.","sammanfattning":"Läser."}'])
    assert results == ["ok"] and v.said[0] == "Hur mår du?"


def test_check_up_asks_again_when_silent_then_gives_up():
    results, v = check_up([], [])
    assert results == ["inget"] and len(v.said) == 3       # fråga, fråga igen, "får inget svar"

"""
Språk-AI:n: förstår vad personen säger och bestämmer vad som ska hända.

Använder i tur och ordning:  Claude (om API-nyckel finns)  ->  Ollama (lokalt)  ->  ordlista
Om AI:n strular mitt i ett samtal tar ordlistan över – det blir aldrig "inget larm" pga ett AI-fel.
"""

import json
import re

import requests

import config as cfg

DECIDE_PROMPT = """Du är röstassistenten i ett fallarm för en äldre person som bor hemma.
En kamera har sett personen ramla, och personen ligger nu ner. Du pratar med personen
via högtalare och mikrofon. Det personen säger har gjorts om till text av en taligenkänning
som ibland hör fel – tolka välvilligt.

Svara ENDAST med JSON i exakt detta format:
{"beslut": "ok" | "hjälp" | "fråga", "säg": "...", "sammanfattning": "..."}

beslut:
- "ok"    = personen säger tydligt att hen mår bra och inte behöver hjälp.
- "hjälp" = personen ber om hjälp, är skadad, har ont, inte kan resa sig, verkar förvirrad eller orolig.
- "fråga" = svaret är otydligt – ställ en kort, enkel följdfråga.
Är du osäker mellan "ok" och "hjälp": välj "hjälp". Säkerheten går alltid först.

säg: det du säger högt till personen. Max två korta meningar, lugn och enkel svenska.
     Vid "hjälp": säg att du larmar nu och att hjälp är på väg.
     Vid "ok": bekräfta vänligt att du inte larmar.
sammanfattning: en mening till anhöriga om vad personen sa och hur hen mår,
     t.ex. "Säger att hon har ont i höften och inte kan resa sig."
"""

SUMMARIZE_PROMPT = """Du hjälper ett fallarm. Personen har ramlat och larmet är redan skickat.
Nedan är vad personen sa när hen fick frågan om vad som hänt. Skriv EN kort mening till anhöriga
om vad som hänt och hur personen mår (t.ex. skada, var det gör ont, om hen pratar klart).
Svara bara med meningen, inget annat."""


def classify_answer(text):
    """Reserv: tolkar svaret med en ordlista. Ger "hjälp", "ok" eller "inget"."""
    t = text.lower().strip()
    if not t or any(h in t for h in cfg.HALLUCINATIONS):
        return "inget"
    words = set(re.findall(r"[a-zåäöé]+", t))
    if words & cfg.HELP_WORDS or any(p in t for p in cfg.HELP_PHRASES):
        return "hjälp"           # "hjälp" vinner alltid, även om "nej" också sägs
    if words & cfg.OK_WORDS or any(p in t for p in cfg.OK_PHRASES):
        return "ok"
    return "inget"


def is_call_for_help(text):
    """Ropar någon på hjälp? Används av lyssnaren som är igång hela tiden, så den är strängare än
    classify_answer – "ja" eller "ont" räcker inte när ingen har ställt en fråga."""
    t = text.lower().strip()
    if not t or any(h in t for h in cfg.HALLUCINATIONS):
        return False
    words = set(re.findall(r"[a-zåäöé0-9]+", t))
    return bool(words & cfg.CALL_WORDS) or any(p in t for p in cfg.CALL_PHRASES)


class Brain:
    def __init__(self):
        self.kind = self._detect()
        label = {"claude": f"Claude ({cfg.CLAUDE_MODEL})",
                 "ollama": f"Ollama ({cfg.OLLAMA_MODEL}, lokalt)",
                 "ordlista": "ordlista (ingen språk-AI hittad – se README)"}[self.kind]
        print(f"Språk-AI: {label}")

    @staticmethod
    def _detect():
        if cfg.ANTHROPIC_API_KEY:
            return "claude"
        try:
            models = requests.get(f"{cfg.OLLAMA_URL}/api/tags", timeout=2).json().get("models", [])
            wanted = cfg.OLLAMA_MODEL.split(":")[0]
            if any(m["name"].split(":")[0] == wanted for m in models):
                return "ollama"
            print(f"OBS: Ollama körs men modellen saknas. Kör:  ollama pull {cfg.OLLAMA_MODEL}")
        except Exception:
            pass
        return "ordlista"

    def _chat(self, system, user):
        if self.kind == "claude":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=20,
                              headers={"x-api-key": cfg.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              json={"model": cfg.CLAUDE_MODEL, "max_tokens": 300, "system": system,
                                    "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        if self.kind == "ollama":
            r = requests.post(f"{cfg.OLLAMA_URL}/api/chat", timeout=40,
                              json={"model": cfg.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0},
                                    "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["message"]["content"]
        raise RuntimeError("ingen språk-AI")

    def decide(self, history):
        """history = [("Datorn", "..."), ("Personen", "..."), ...]
        Returnerar {"beslut": "ok"/"hjälp"/"fråga", "säg": ..., "sammanfattning": ...}"""
        last = history[-1][1]
        if self.kind != "ordlista":
            try:
                raw = self._chat(DECIDE_PROMPT, "\n".join(f"{who}: {txt}" for who, txt in history))
                match = re.search(r"\{.*\}", raw, re.S)
                if not match:
                    raise ValueError(f"inget JSON i svaret: {raw[:80]!r}")
                d = json.loads(match.group(0))
                if d.get("beslut") in ("ok", "hjälp", "fråga") and d.get("säg"):
                    d.setdefault("sammanfattning", f'Personen sa: "{last}"')
                    return d
                raise ValueError(f"konstigt svar: {raw[:80]!r}")
            except Exception as e:
                print(f"  !! Språk-AI:n misslyckades ({e}) – använder ordlistan")
        return self._decide_with_wordlist(last)

    @staticmethod
    def _decide_with_wordlist(said):
        result = classify_answer(said)
        summary = f'Personen sa: "{said}"'
        if result == "ok":
            return {"beslut": "ok", "säg": "Okej, vad skönt. Då larmar jag inte.", "sammanfattning": summary}
        if result == "hjälp":
            return {"beslut": "hjälp", "säg": "Jag larmar nu. Hjälp är på väg.", "sammanfattning": summary}
        return {"beslut": "fråga", "säg": "Jag förstod inte riktigt. Behöver du hjälp? Säg ja eller nej.",
                "sammanfattning": summary}

    def summarize(self, said):
        """Gör om det personen berättat efter larmet till en mening för anhöriga."""
        if self.kind != "ordlista":
            try:
                return self._chat(SUMMARIZE_PROMPT, said).strip()
            except Exception as e:
                print(f"  !! Språk-AI:n misslyckades ({e})")
        return f'Personen sa: "{said}"'

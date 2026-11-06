"""
Rösten: prata, lyssna, göra om tal till text (Whisper) och föra ett samtal efter ett fall.
Lyssnar också hela tiden efter rop på hjälp, så att det går att larma även utan att kameran sett ett fall.
"""

import asyncio
import contextlib
import os
import subprocess
import tempfile
import threading
import time

import numpy as np

import config as cfg
from brain import Brain, camera_command, classify_answer, is_call_for_help


def pick_swedish_voice():
    """Väljer den bästa svenska rösten som finns i macOS: Premium > Förbättrad > vanlig."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    except Exception:
        return None
    best, best_score = None, 0
    for line in out.splitlines():
        if "sv_SE" not in line:
            continue
        name = line.split("sv_SE")[0].strip()
        low = name.lower()
        score = 3 if "premium" in low else 2 if ("enhanced" in low or "förbättrad" in low) else 1
        if cfg.VOICE_NAME.lower() in low:
            score += 0.5
        if score > best_score:
            best, best_score = name, score
    return best


def is_thud(audio):
    """En smäll: en kort bit (50 ms) som är mycket högre än ljudet runt omkring."""
    n = 800                                     # 50 ms vid 16 kHz
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    if len(frames) == 0:
        return False
    rms = np.sqrt((frames ** 2).mean(axis=1))
    peak = float(rms.max())
    return peak >= cfg.THUD_LEVEL and peak >= cfg.THUD_RATIO * max(float(np.median(rms)), 1e-4)


class VoiceCheck:
    def __init__(self, model_size=None, brain=None):
        self.model = None
        self.model_size = model_size or cfg.WHISPER_MODEL
        self.brain = brain or Brain()
        self._init_sync()
        self.mac_voice = pick_swedish_voice()
        self.use_neural = cfg.NEURAL_VOICE and self._has_edge_tts()

        if self.use_neural:
            print(f"Röst: {cfg.EDGE_VOICE} (neural, kräver internet – reserv: {self.mac_voice or 'standardrösten'})")
        elif self.mac_voice:
            print(f"Röst: {self.mac_voice} (macOS)")
        else:
            print("OBS: Ingen svensk röst i macOS hittades – se README.")

        threading.Thread(target=self._load_whisper, daemon=True).start()

    def _init_sync(self):
        self.speak_lock = threading.Lock()     # två saker ska inte prata samtidigt
        self.mic_lock = threading.Lock()       # två saker ska inte spela in samtidigt
        self.busy_lock = threading.Lock()
        self.busy_count = 0                    # > 0 medan ett samtal pågår – då pausar lyssnaren
        self.last_spoke = 0.0                  # när datorn senast pratade klart

    @contextlib.contextmanager
    def _busy(self):
        with self.busy_lock:
            self.busy_count += 1
        try:
            yield
        finally:
            with self.busy_lock:
                self.busy_count -= 1

    @staticmethod
    def _has_edge_tts():
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    # ---- Whisper (tal -> text) ----

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        print(f"Laddar tal-AI (Whisper '{self.model_size}', första gången laddas den ner)...")
        self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        print("Tal-AI redo.")

    def wait_until_ready(self, max_seconds=600):
        start = time.time()
        while self.model is None and time.time() - start < max_seconds:
            time.sleep(0.5)

    # ---- prata ----

    def say(self, text):
        print(f'  [SÄGER] "{text}"')
        with self.speak_lock:
            try:
                if self.use_neural:
                    try:
                        self._say_neural(text)
                        return
                    except Exception as e:
                        print(f"  !! Neurala rösten funkade inte ({e}) – använder macOS-rösten")
                subprocess.run(["say"] + (["-v", self.mac_voice] if self.mac_voice else []) + [text])
            finally:
                self.last_spoke = time.time()

    @staticmethod
    def _say_neural(text):
        import edge_tts
        path = os.path.join(tempfile.gettempdir(), "fallvakt_tal.mp3")
        asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, cfg.EDGE_VOICE).save(path), timeout=10))
        subprocess.run(["afplay", path], check=True)

    # ---- lyssna ----

    def listen(self, seconds=None, quiet=False):
        import sounddevice as sd
        if not quiet:
            print("  [RÖST] Lyssnar...")
        with self.mic_lock:
            audio = sd.rec(int((seconds or cfg.LISTEN_SECONDS) * 16000), samplerate=16000, channels=1,
                           dtype="float32")
            sd.wait()
        return audio.flatten()

    def transcribe(self, audio):
        if float(np.sqrt(np.mean(audio ** 2))) < cfg.SILENCE_LEVEL:
            return ""                           # helt tyst
        self.wait_until_ready(60)
        if self.model is None:
            return ""
        segments, _ = self.model.transcribe(audio, language="sv", vad_filter=True, beam_size=5)
        text = " ".join(s.text for s in segments).strip()
        if any(h in text.lower() for h in cfg.HALLUCINATIONS):
            return ""
        print(f'  [RÖST] Hörde: "{text}"')
        return text

    # ---- samtalet ----

    def converse(self, attempt, first_question=None, situation=None):
        """Ett samtal med personen. Returnerar (resultat, sammanfattning, sista_repliken).
        Utan first_question/situation handlar samtalet om ett fall."""
        question = ((first_question or "Hej! Det ser ut som att du har ramlat. Hur mår du? Behöver du hjälp?")
                    if attempt == 1 else "Jag hörde inget svar. Behöver du hjälp? Säg ja eller nej.")
        history = []
        for turn in range(cfg.MAX_TURNS):
            self.say(question)
            history.append(("Datorn", question))
            said = self.transcribe(self.listen())
            if not said:
                last = "Jag får inget svar, så jag larmar nu." if attempt >= cfg.VOICE_ATTEMPTS else None
                return "inget", "Personen svarar inte.", last
            history.append(("Personen", said))

            d = self.brain.decide(history, situation)
            print(f"  [AI] {d['beslut']} – {d['sammanfattning']}")
            if d["beslut"] == "fråga":
                if turn < cfg.MAX_TURNS - 1:
                    question = d["säg"]
                    continue
                # fortfarande oklart efter flera frågor -> larma hellre
                return "hjälp", d["sammanfattning"] + " (oklart svar)", "Jag larmar för säkerhets skull. Hjälp är på väg."
            return d["beslut"], d["sammanfattning"], d["säg"]
        return "hjälp", "Oklart samtal.", "Jag larmar för säkerhets skull."

    def followup(self):
        """Efter larmet: fråga vad som hänt. Returnerar en mening till anhöriga (eller None)."""
        self.say("Kan du berätta vad som har hänt, och om du har ont någonstans?")
        said = self.transcribe(self.listen())
        return self.brain.summarize(said) if said else None

    def ask_in_background(self, attempt, on_result, on_followup=None):
        """Kör samtalet i en egen tråd så att kameran inte fryser. Lyssnaren pausar under tiden."""
        def run():
            with self._busy():
                talk()

        def talk():
            try:
                result, summary, last_line = self.converse(attempt)
            except Exception as e:
                print(f"  !! Röstkollen kraschade: {e}")
                result, summary, last_line = "inget", "Röstkollen kraschade.", None
            self._finish(result, summary, last_line, on_result, on_followup)
        threading.Thread(target=run, daemon=True).start()

    def _finish(self, result, summary, last_line, on_result, on_followup):
        on_result(result, summary)               # larma FÖRST...
        if last_line:
            self.say(last_line)                  # ...prata sen
        if result == "hjälp" and on_followup:
            try:
                info = self.followup()
                if info:
                    on_followup(info)
                    self.say("Tack. Jag har skickat det till dina anhöriga.")
            except Exception as e:
                print(f"  !! Följdfrågan kraschade: {e}")

    def check_up(self, question, situation, on_result, on_followup=None):
        """Koll av hur personen mår (inaktivitet eller daglig koll). Frågar igen om hen är tyst."""
        with self._busy():
            result, summary, last_line = "inget", "Personen svarar inte.", None
            for attempt in range(1, cfg.VOICE_ATTEMPTS + 1):
                try:
                    result, summary, last_line = self.converse(attempt, question, situation)
                except Exception as e:
                    print(f"  !! Kollen kraschade: {e}")
                    result, summary, last_line = "inget", "Röstkollen kraschade.", None
                    break
                if result != "inget":
                    break
            self._finish(result, summary, last_line, on_result, on_followup)

    def check_up_in_background(self, question, situation, on_result, on_followup=None):
        threading.Thread(target=self.check_up, args=(question, situation, on_result, on_followup),
                         daemon=True).start()

    # ---- lyssnar hela tiden efter rop på hjälp ----

    def handle_call(self, heard, on_help, on_followup=None):
        """Någon ropade på hjälp. Dubbelkolla en gång – tyst eller oklart svar larmar ändå."""
        with self._busy():
            print(f'[RÖST] Rop på hjälp: "{heard}"')
            self.say("Jag hörde att du behöver hjälp. Ska jag larma? Säg nej om allt är bra.")
            answer = self.transcribe(self.listen())
            if answer and classify_answer(answer) == "ok":
                self.say("Okej, då larmar jag inte.")
                return False
            on_help(f'Personen ropade: "{heard}"' + (f' och svarade: "{answer}"' if answer else ""))
            self.say("Jag larmar nu. Hjälp är på väg.")
            if on_followup:
                try:
                    info = self.followup()
                    if info:
                        on_followup(info)
                        self.say("Tack. Jag har skickat det till dina anhöriga.")
                except Exception as e:
                    print(f"  !! Följdfrågan kraschade: {e}")
            return True

    def listen_for_help_in_background(self, on_help, on_followup=None, on_call=None, on_thud=None,
                                      on_command=None):
        """Lyssnar hela tiden i en egen tråd. Pausar medan datorn pratar eller ett samtal pågår.
        on_call() = någon ropade (innan kontrollfrågan), on_thud() = en smäll,
        on_command("paus"/"på") = personen vill pausa eller slå på kameran."""
        def run():
            self.wait_until_ready()
            print("Lyssnar efter rop på hjälp.")
            while True:
                try:
                    if self.busy_count or self.speak_lock.locked():
                        time.sleep(0.3)
                        continue
                    started = time.time()
                    audio = self.listen(cfg.CALL_LISTEN_SECONDS, quiet=True)
                    # Datorn pratade under inspelningen – det var nog den själv vi hörde ("Hjälp är på väg")
                    if self.busy_count or self.speak_lock.locked() or self.last_spoke > started - 1:
                        continue
                    if on_thud and is_thud(audio):
                        print("[LJUD] Hörde en smäll")
                        on_thud()
                    heard = self.transcribe(audio)
                    if not heard:
                        continue
                    if is_call_for_help(heard):
                        if on_call:
                            on_call()
                        self.handle_call(heard, on_help, on_followup)
                    elif on_command and camera_command(heard):
                        on_command(camera_command(heard))
                except Exception as e:
                    print(f"  !! Lyssnaren: {e}")
                    time.sleep(2)
        threading.Thread(target=run, daemon=True).start()

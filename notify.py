"""
Allt som går ut till mobilen: notiser (Telegram, ntfy), samtal (Twilio)
– och svaren som kommer tillbaka från anhöriga i Telegram.

Allt skickas i bakgrundstrådar så att kameran inte fryser.
"""

import json
import threading
import time
from xml.sax.saxutils import escape

import requests

import config as cfg

ALARM_BUTTONS = {"inline_keyboard": [[
    {"text": "🏃 Jag kommer", "callback_data": "kommer"},
    {"text": "✅ Falsklarm", "callback_data": "falsk"},
]]}


def _in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def telegram_configured():
    return bool(cfg.TELEGRAM_TOKEN and cfg.TELEGRAM_CHAT_ID)


def twilio_configured():
    return bool(cfg.TWILIO_SID and cfg.TWILIO_TOKEN and cfg.TWILIO_FROM and cfg.CALL_TO)


# =====================================================================
# Notiser
# =====================================================================

def send_alarm(message, jpg_bytes=None, urgent=True, buttons=True):
    """Skickar till Telegram (med bild och knappar) och ntfy."""
    print(f"[{'LARM' if urgent else 'INFO'}] {message}")

    def _send():
        sent = False
        if telegram_configured():
            try:
                base = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}"
                data = {"chat_id": cfg.TELEGRAM_CHAT_ID}
                if buttons:
                    data["reply_markup"] = json.dumps(ALARM_BUTTONS)
                if jpg_bytes:
                    r = requests.post(f"{base}/sendPhoto", timeout=10, data={**data, "caption": message},
                                      files={"photo": ("fall.jpg", jpg_bytes, "image/jpeg")})
                else:
                    r = requests.post(f"{base}/sendMessage", timeout=10, data={**data, "text": message})
                r.raise_for_status()
                sent = True
                print("  -> Telegram skickat")
            except Exception as e:
                print(f"  !! Telegram misslyckades: {e}")
        if cfg.NTFY_TOPIC:
            try:
                headers = {"Title": "Fallvakt"}
                if urgent:
                    headers.update({"Priority": "urgent", "Tags": "rotating_light"})
                requests.post(f"https://ntfy.sh/{cfg.NTFY_TOPIC}", data=message.encode("utf-8"),
                              headers=headers, timeout=10)
                sent = True
                print("  -> ntfy skickat")
            except Exception as e:
                print(f"  !! ntfy misslyckades: {e}")
        if not sent:
            print("  (Ingen larmkanal inställd – fyll i .env, se README)")

    _in_background(_send)


def send_info(message):
    """Vanligt meddelande, utan knappar och utan att låta som ett larm."""
    send_alarm(message, urgent=False, buttons=False)


# =====================================================================
# Samtal
# =====================================================================

def call_phone(message):
    """Ringer CALL_TO via Twilio. En svensk röst läser upp meddelandet två gånger."""
    if not twilio_configured():
        return
    twiml = ('<Response><Pause length="1"/>'
             f'<Say language="sv-SE" voice="Polly.Astrid" loop="2">{escape(message)}</Say>'
             '</Response>')

    def _call():
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{cfg.TWILIO_SID}/Calls.json",
                              auth=(cfg.TWILIO_SID, cfg.TWILIO_TOKEN), timeout=20,
                              data={"To": cfg.CALL_TO, "From": cfg.TWILIO_FROM, "Twiml": twiml})
            if r.ok:
                print(f"  -> Ringer {cfg.CALL_TO}")
            else:
                print(f"  !! Samtalet misslyckades ({r.status_code}): {r.json().get('message', r.text)}")
        except Exception as e:
            print(f"  !! Samtalet misslyckades: {e}")

    _in_background(_call)


# =====================================================================
# Svar från anhöriga
# =====================================================================

class TelegramChat:
    """Lyssnar efter knapptryck och meddelanden i Telegram och skickar dem till on_message(typ, text)."""

    def __init__(self, on_message):
        self.on_message = on_message
        self.base = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}"
        self.offset = None
        _in_background(self._loop)
        print("Telegram: lyssnar efter svar från anhöriga.")

    def reply(self, text):
        try:
            requests.post(f"{self.base}/sendMessage", timeout=10,
                          data={"chat_id": cfg.TELEGRAM_CHAT_ID, "text": text})
        except Exception:
            pass

    def _is_ours(self, chat):
        return str(chat["id"]) == str(cfg.TELEGRAM_CHAT_ID)

    def _loop(self):
        # Hoppa över gamla meddelanden från innan programmet startade
        try:
            old = requests.get(f"{self.base}/getUpdates", params={"offset": -1}, timeout=10).json()
            if old.get("result"):
                self.offset = old["result"][-1]["update_id"] + 1
        except Exception:
            pass

        while True:
            try:
                updates = requests.get(f"{self.base}/getUpdates", timeout=35,
                                       params={"timeout": 30, "offset": self.offset}).json()
                for u in updates.get("result", []):
                    self.offset = u["update_id"] + 1
                    if "callback_query" in u:                         # knapptryck
                        cq = u["callback_query"]
                        if self._is_ours(cq["message"]["chat"]):
                            requests.post(f"{self.base}/answerCallbackQuery", timeout=10,
                                          data={"callback_query_id": cq["id"], "text": "Mottaget ✅"})
                            self.on_message("knapp", cq["data"])
                    elif "text" in u.get("message", {}):               # vanligt meddelande
                        msg = u["message"]
                        if self._is_ours(msg["chat"]) and not msg["text"].startswith("/"):
                            self.on_message("text", msg["text"])
            except Exception as e:
                print(f"  !! Telegram-lyssning: {e}")
                time.sleep(5)


def handle_relative_message(kind, text, voice, detector, chat):
    """Vad som händer när en anhörig trycker på en knapp eller skriver i Telegram."""
    if kind == "knapp" and text == "kommer":
        line = f"{cfg.ANHORIG_NAMN} har sett larmet och är på väg. Försök ligga still, hjälpen kommer snart."
    elif kind == "knapp" and text == "falsk":
        if detector:
            detector.cancel_alarm()
        line = "Okej, larmet är avstängt."
    elif kind == "text":
        line = f"Meddelande från {cfg.ANHORIG_NAMN}: {text}"
    else:
        return
    print(f"[TELEGRAM] {kind}: {text}")
    if voice:
        voice.say(line)
        chat.reply(f'🔊 Uppläst: "{line}"')
    else:
        chat.reply("(Röstkollen är avstängd – meddelandet lästes inte upp)")

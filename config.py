"""
Alla inställningar på ett ställe.

Hemliga saker (nycklar, telefonnummer) ligger i filen .env bredvid den här filen.
Allt annat skruvar du på här nedanför.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass  # utan python-dotenv läses bara vanliga miljövariabler


def _env(name, default=""):
    return os.getenv(name, default)


# =====================================================================
# Nycklar och kontakter – läses från .env
# =====================================================================

TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
NTFY_TOPIC = _env("NTFY_TOPIC")

TWILIO_SID = _env("TWILIO_SID")
TWILIO_TOKEN = _env("TWILIO_TOKEN")
TWILIO_FROM = _env("TWILIO_FROM")        # ditt Twilio-nummer, t.ex. +16205551234
CALL_TO = _env("CALL_TO")                # numret som ska ringas, t.ex. +46701234567

ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")   # finns den används Claude som språk-AI
ANHORIG_NAMN = _env("ANHORIG_NAMN", "Olle")     # namnet som sägs när en anhörig svarar


# =====================================================================
# Fall-detektering
# =====================================================================

DROP_SPEED = 0.4            # Hur snabbt höften måste röra sig nedåt (bildhöjder/sekund). Kameran långt bort? Prova 0.25
SPEED_WINDOW = 0.5          # Över hur många sekunder farten mäts
LYING_ANGLE = 60            # Överkroppen lutar mer än så (grader från lodrätt) = liggande
LYING_ASPECT = 1.3          # ...eller kroppens ruta är så här mycket bredare än hög = liggande
DROP_TO_LYING_WINDOW = 2.0  # Efter ett snabbt fall måste personen bli liggande inom så här många sekunder
STILL_DOWN_SECONDS = 10     # Utan röstkoll: så länge personen måste ligga kvar innan larm
UPRIGHT_RESET_SECONDS = 3   # Så länge personen måste stå/sitta upp för att larmet ska återställas
ALARM_COOLDOWN = 120        # Minsta tid mellan två larm (sekunder)
MIN_KP_CONF = 0.4           # Hur säker AI:n måste vara på en kroppspunkt för att den ska användas


# =====================================================================
# Röstkollen
# =====================================================================

ASK_AFTER_SECONDS = 5       # Efter så här många sekunder på golvet frågar datorn hur personen mår
LISTEN_SECONDS = 6          # Hur länge den lyssnar efter svar
VOICE_ATTEMPTS = 2          # Hur många gånger den frågar om personen är tyst, innan den larmar
MAX_TURNS = 3               # Max antal frågor i ett samtal innan den larmar för säkerhets skull
VOICE_TIMEOUT = 60          # Säkerhetsspärr: larma om röstkollen av någon anledning inte blir klar
RECHECK_AFTER = 120         # Svarade "okej" men ligger kvar? Fråga igen efter så här många sekunder
SILENCE_LEVEL = 0.002       # Ljudnivå under detta räknas som tystnad

ALWAYS_LISTEN = _env("ALWAYS_LISTEN", "1") != "0"   # Lyssna hela tiden efter rop på hjälp, även utan fall
CALL_LISTEN_SECONDS = 4     # Hur långa bitar ljud den lyssnar på åt gången
CALL_WORDS = {"hjälp", "ambulans", "112"}           # Ett av de här orden = rop på hjälp
CALL_PHRASES = ["hjälpa mig", "jag har ramlat", "jag har trillat", "jag har fallit",
                "kommer inte upp", "jag kan inte resa mig"]

WHISPER_MODEL = "small"   # Tal-AI: "base" (snabb), "small" (standard), "medium" (bäst svenska, långsam)

VOICE_NAME = "Alva"                                     # Föredragen macOS-röst (reserv)
NEURAL_VOICE = _env("NEURAL_VOICE", "1") != "0"         # Använd Microsofts neurala röst (kräver internet)
EDGE_VOICE = _env("EDGE_VOICE", "sv-SE-SofieNeural")    # eller sv-SE-MattiasNeural


# =====================================================================
# Språk-AI
# =====================================================================

CLAUDE_MODEL = "claude-haiku-5-5"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = _env("OLLAMA_MODEL", "gemma3:4b")


# =====================================================================
# Reserv-ordlistan (används om ingen språk-AI finns)
# =====================================================================

HELP_WORDS = {"ja", "jo", "japp", "hjälp", "hjälpa", "ont", "ambulans", "ring", "aj", "snälla"}
HELP_PHRASES = ["kan inte", "klarar inte", "kommer inte upp"]
OK_WORDS = {"nej", "nä", "nää", "okej", "ok", "okay", "bra", "fint", "lugnt"}
OK_PHRASES = ["mår bra", "klarar mig"]
# Whisper "hör" ibland de här fraserna när det är tyst
HALLUCINATIONS = ["tack för att du tittade", "textning", "undertext", "prenumerera", "tack för att ni"]

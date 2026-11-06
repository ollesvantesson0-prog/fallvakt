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
# Inaktivitetskoll och rutiner (routine.py)
# =====================================================================

INACTIVITY_CHECK = _env("INACTIVITY_CHECK", "1") != "0"  # Fråga hur personen mår om hen varit stilla länge
MOVE_THRESHOLD = 0.02       # Så mycket kroppspunkterna måste flytta sig (andel av bilden) för att räknas som rörelse
MOVE_INTERVAL = 1.0         # Jämför kroppspunkterna med hur de låg för så här många sekunder sedan
INACTIVITY_LIMIT = 20       # Koll när så här många "rörelseminuter" brukar ha hänt men inte gjort det (≈ 2 tim på dagen)
LYING_STILL_LIMIT = 5       # Samma sak när personen ligger ner (≈ 30 min på dagen)
INACTIVITY_MIN_MINUTES = 20 # Frågar aldrig tidigare än så här
INACTIVITY_MAX_HOURS = 14   # ...och alltid efter så här lång tid utan rörelse, oavsett tid på dygnet

DEFAULT_AWAKE = (7, 22)     # Innan den lärt sig: personen antas vara vaken 07–22
DEFAULT_ACTIVE_RATE = 10    # ...med så här många rörelseminuter per timme
DEFAULT_NIGHT_RATE = 0.5    # ...och så här få på natten
LEARN_MIN_DAYS = 3          # Så många dagar innan det inlärda dygnet används
LEARN_DAYS = 14             # Rutinerna är ett medel av ungefär så här många dagar
LEARN_MIN_WATCHED = 2700    # En timme räknas bara om kameran var igång minst så många sekunder av den

CHECKUP_TIMES = _env("CHECKUP_TIMES", "")   # Dagliga koller, t.ex. "10:00,16:00". Tomt = av


# =====================================================================
# Kameran och integritet (camera.py)
# =====================================================================

CAMERA_MODE = _env("CAMERA_MODE", "alltid")     # "alltid", "tider" eller "vid_misstanke"
CAMERA_HOURS = _env("CAMERA_HOURS", "22-08")    # För "tider": när kameran är på, t.ex. "22-08" eller "22-08,13-15"
WAKE_MINUTES = 3            # Så länge kameran är på efter en misstanke (smäll, rop på hjälp, inget svar)
MANUAL_HOURS = 2            # Så länge "pausa kameran" / "slå på kameran" gäller
ALARM_IMAGE = _env("ALARM_IMAGE", "streckgubbe")  # Bilden i larmet: "streckgubbe" eller "foto"

THUD_LEVEL = 0.2            # Så hög ljudnivå en smäll måste ha. Missar den smällar? Sänk. Startar den av allt? Höj
THUD_RATIO = 8              # ...och så många gånger högre än ljudet runt omkring

PAUSE_PHRASES = ["pausa kameran", "stäng av kameran", "stänga av kameran", "stäng kameran",
                 "fallvakt paus", "fall vakt paus"]
RESUME_PHRASES = ["slå på kameran", "sätt på kameran", "sätta på kameran", "starta kameran",
                  "fallvakt på", "fall vakt på"]


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

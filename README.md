# Fallvakt 🛟

Kameran ser att någon ramlar → datorn frågar hur personen mår → en AI förstår svaret → larm till mobilen och ett samtal till dig.
Ropar någon på hjälp larmar den också – även om kameran inte sett något fall.

## Projektets delar

| Fil | Vad den gör |
|---|---|
| `main.py` | Startar allt och kopplar ihop delarna. **Det är den du kör.** |
| `config.py` | **Alla inställningar.** Här ändrar du känslighet, röst, tider osv. |
| `.env` | **Dina hemliga nycklar** (Telegram, Twilio …). Dela den aldrig. |
| `detector.py` | Fall-logiken: kroppspunkter → "har personen ramlat?" |
| `voice.py` | Prata, lyssna, Whisper (tal → text), samtalet efter ett fall, lyssnar efter rop på hjälp |
| `brain.py` | Språk-AI:n som förstår svaret (Claude / Ollama / ordlista) |
| `notify.py` | Telegram, ntfy, samtal via Twilio, svar från anhöriga |
| `tests/` | Tester som kollar att allt funkar, utan kamera eller mikrofon |

## Köra

```bash
source .venv/bin/activate
python main.py
```

| Kommando | Vad det gör |
|---|---|
| `python main.py --debug` | Visar fart, vinkel och status i terminalen |
| `python main.py --test-alarm` | Testlarm och testsamtal, väntar 60 s på knapptryck i Telegram |
| `python main.py --test-voice` | Testar röstsamtalet utan att ramla |
| `python main.py --no-voice` | Utan röst, larmar efter 10 s på golvet |
| `python main.py --list-cameras` | Visar vilka kameror som finns |
| `pytest` | Kör alla tester. Gör det efter att du ändrat i koden |

**I kamerafönstret:** `q` avslutar, `p` slår integritetsläget av/på (bara streckgubbe), `t` skickar ett testlarm.

## Hur fall-logiken funkar

| Status | Betyder | Går vidare när … |
|---|---|---|
| **OK** | Allt normalt | höften rör sig snabbt nedåt → MÖJLIGT FALL |
| **MÖJLIGT FALL** | Snabb rörelse nedåt | personen ligger ner (eller försvinner ur bild) inom 2 s → LIGGER KVAR, annars OK |
| **LIGGER KVAR** | Ligger på golvet | efter 5 s → FRÅGAR |
| **FRÅGAR** | Datorn frågar "Hur mår du?" | mår bra → SVARADE OK · behöver hjälp → LARM · tyst två gånger → LARM |
| **SVARADE OK** | Personen klarar sig | står upp → OK · ligger kvar 2 min → frågar igen |
| **LARM** | Notis och samtal skickat | står upp i 3 s → OK, och du får "Personen har rest sig" |

Reser sig personen innan larmet går blir det aldrig något larm.

## Rop på hjälp

Mikrofonen lyssnar hela tiden (pausar när datorn själv pratar). Säger någon t.ex. **"hjälp"**, **"ring ambulans"**, **"jag har ramlat"** eller **"jag kommer inte upp"** frågar datorn:

> "Jag hörde att du behöver hjälp. Ska jag larma? Säg nej om allt är bra."

| Svar | Vad som händer |
|---|---|
| "Nej" / "det är bra" | Inget larm |
| "Ja", något annat, eller tyst | **LARM** (notis + samtal), sen frågar den vad som hänt |

Orden finns i `CALL_WORDS` och `CALL_PHRASES` i `config.py`. Stäng av med `ALWAYS_LISTEN=0` i `.env`. Obs: tv/radio som säger "hjälp" kan ge larm om ingen svarar nej.

## Justera känsligheten (i `config.py`)

| Inställning | Standard | Höj om … | Sänk om … |
|---|---|---|---|
| `DROP_SPEED` | 0.4 | den larmar när du sätter dig | den missar riktiga fall |
| `LYING_ANGLE` | 60 | den tror att du ligger när du lutar dig | den inte märker att du ligger |
| `ASK_AFTER_SECONDS` | 5 | den frågar för tidigt | du vill att den frågar snabbare |

Kör `pytest` efter ändringar för att se att inget har gått sönder.

## Nycklar (`.env`)

Alla hemliga uppgifter ligger i filen `.env` i projektmappen, en per rad:

```
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
NTFY_TOPIC=...
TWILIO_SID=...
TWILIO_TOKEN=...
TWILIO_FROM=+1...
CALL_TO=+46...
```

Se `.env.example` för alla som finns. Öppna `.env` i VS Code för att ändra. Filen syns inte i Finder eftersom den börjar med en punkt.

## Språk-AI

Programmet väljer automatiskt det första som finns av:
1. **Claude**: om `ANTHROPIC_API_KEY` finns i `.env`. Bäst svenska, kostar några öre per fall.
2. **Ollama**: om Ollama-appen kör och modellen är nedladdad (`ollama pull gemma3:4b`). Gratis och lokalt.
3. **Ordlista**: förstår bara ja, nej och hjälp.

Strular AI:n mitt i ett samtal tar ordlistan över, så det blir aldrig "inget larm" på grund av ett AI-fel.

## Röst

- **Neural röst (standard):** `sv-SE-SofieNeural`, kräver internet. Mansröst: `EDGE_VOICE=sv-SE-MattiasNeural` i `.env`.
- **Reserv utan internet:** den bästa svenska macOS-rösten du har. Ladda ner **Alva (Premium)** under Systeminställningar → Hjälpmedel → Talat innehåll → Systemröst → Hantera röster.

## Samtal (Twilio)

Vid larm ringer Twilio `CALL_TO`, och en svensk röst läser upp vad som hänt. På provkontot säger en engelsk röst först att det är ett provkonto. **Tryck valfri siffra**, så kommer larmet. Det engelska försvinner om kontot uppgraderas till betalt.

## Telegram-knappar

| Knapp | Vad som sägs högt hemma |
|---|---|
| 🏃 **Jag kommer** | "Olle har sett larmet och är på väg …" |
| ✅ **Falsklarm** | "Okej, larmet är avstängt." Larmet återställs |

Allt du skriver till boten läses upp högt.

---

> Hobbyprojekt, inte en certifierad säkerhetsprodukt. Lita inte på det för att skydda någon på riktigt.

# Fallvakt 🛟

Kameran ser att någon ramlar → datorn frågar hur personen mår → en AI förstår svaret → larm till mobilen och ett samtal till dig.
Ropar någon på hjälp larmar den också – även om kameran inte sett något fall.
Har personen varit stilla ovanligt länge frågar datorn hur hen mår. Den lär sig personens dygn.

## Projektets delar

| Fil | Vad den gör |
|---|---|
| `main.py` | Startar allt och kopplar ihop delarna. **Det är den du kör.** |
| `config.py` | **Alla inställningar.** Här ändrar du känslighet, röst, tider osv. |
| `.env` | **Dina hemliga nycklar** (Telegram, Twilio …). Dela den aldrig. |
| `detector.py` | Fall-logiken: kroppspunkter → "har personen ramlat?" |
| `voice.py` | Prata, lyssna, Whisper (tal → text), samtalet efter ett fall, lyssnar efter rop på hjälp |
| `camera.py` | När kameran får vara på: alltid, vissa tider eller vid misstanke |
| `routine.py` | Inaktivitetskoll, inlärda rutiner och dagliga koller |
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
| `python main.py --rutiner` | Visar vad den har lärt sig om personens dygn |
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

## Inaktivitetskoll och rutiner

Kameran håller koll på när personen senast **rörde sig**. Har det varit stilla ovanligt länge frågar datorn:

> "Hej! Jag har inte sett dig röra dig på ett tag. Hur mår du?"

| Svar | Vad som händer |
|---|---|
| "Jag mår bra, jag läser bara" | Inget larm, räknas som rörelse |
| Behöver hjälp | **LARM**, sen frågar den vad som hänt |
| Tyst två gånger | **LARM** ("svarar inte – kan också vara att hen inte är hemma") |

**Hur länge är "ovanligt länge"?** Det beror på tiden på dygnet:

| | Frågar efter ungefär |
|---|---|
| Dagtid, ingen rörelse | 2 timmar |
| Dagtid, ligger ner helt stilla | 30 minuter |
| Natt | mycket senare (men alltid efter 14 timmar) |

**Den lär sig rutinerna.** Varje timme på dygnet sparas hur mycket personen brukar röra sig. Efter 3 dagar används det inlärda dygnet i stället för standarddygnet (vaken 07–22). Brukar hen gå ut 13–16, eller sova till 9, frågar den inte då. Se vad den lärt sig med `python main.py --rutiner`. Det sparas i `rutiner.json` (bara siffror, inga bilder). Ta bort filen för att börja om.

Inställningar i `config.py`: `INACTIVITY_LIMIT` (högre = frågar mer sällan), `LYING_STILL_LIMIT`, `MOVE_THRESHOLD`. Stäng av med `INACTIVITY_CHECK=0` i `.env`.

## Integritet: kameran behöver inte vara på hela tiden

Välj läge i `.env`:

```
CAMERA_MODE=alltid          # alltid på (standard)
CAMERA_MODE=tider           # bara vissa tider, se CAMERA_HOURS
CAMERA_HOURS=22-08          # t.ex. natten, eller flera: 22-08,13-15
CAMERA_MODE=vid_misstanke   # av, startar bara när något verkar fel
```

**Vid misstanke** startar kameran i 3 minuter (`WAKE_MINUTES`) när:

| Det här händer | Vad kameran gör |
|---|---|
| Mikrofonen hör en **smäll** | Startar. Ligger personen ner = som ett fall (frågar hur hen mår). Syns ingen frågar den "Jag hörde en smäll. Är allt bra?" |
| Någon **ropar på hjälp** | Startar, så att larmet får en bild |
| Ingen svarar på **dagens koll** | Startar och ser efter om personen ligger ner |

**Personen bestämmer själv**, i alla lägen:

| Säg | Vad som händer |
|---|---|
| "Pausa kameran" / "Stäng av kameran" | Av i 2 timmar (`MANUAL_HOURS`). Du får ett meddelande om det |
| "Slå på kameran" | På igen |

Under en paus startar inte kameran ens vid en smäll. Då frågar datorn med rösten i stället. Rop på hjälp larmar alltid.

**Anhöriga i Telegram:** `/paus 3` (pausa i 3 tim), `/på`, `/status`. Det som ändras sägs alltid **högt hemma**, så ingen blir övervakad i smyg.

**Annat som skyddar integriteten**
- Lampan bredvid Mac-kameran lyser när kameran är på. Det går inte att fuska med.
- Larmbilden är en **streckgubbe** på svart (`ALARM_IMAGE=foto` för riktig bild).
- Allt körs på datorn. Inget filmas eller sparas. Mikrofonen gör om tal till text lokalt och sparar inget.
- Pågår ett larm eller en koll stängs kameran aldrig av mitt i.

Bra att veta: med kameran av märks ett tyst fall (ingen smäll, inget rop) bara av den dagliga kollen, och inaktivitetskollen vilar. Smällen hörs bara medan mikrofonen lyssnar, inte under de sekunder Whisper tolkar ljudet. Är smäll-känsligheten fel, justera `THUD_LEVEL` i `config.py` (terminalen skriver `[LJUD] Hörde en smäll`).

## Dagliga koller

Vill du att datorn frågar hur personen mår vid fasta tider, skriv in tiderna i `.env`:

```
CHECKUP_TIMES=10:00,16:00
```

Du får ett lugnt meddelande, t.ex. *"☀️ Dagens koll 10:00: mår bra. Säger att hon sovit gott."* Larm blir det bara om personen säger att hen behöver hjälp. Svarar ingen får du ett meddelande om det.

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

#!/usr/bin/env python3
"""
FALLVAKT – startar allt och kopplar ihop delarna.

  python main.py                  kör (laptopens kamera)
  python main.py --debug          kör och skriv ut fart/vinkel/status i terminalen
  python main.py --source 1       annan kamera
  python main.py --test-alarm     skicka testlarm + testsamtal, vänta 60 s på svar i Telegram
  python main.py --test-voice     testa röstsamtalet utan att ramla
  python main.py --no-voice       utan röstkoll (larmar efter 10 s på golvet)
  python main.py --list-cameras   visa vilka kameror som finns
  python main.py --rutiner        visa vad den har lärt sig om personens dygn

Kameran kan vara på alltid, vissa tider eller bara vid misstanke – se CAMERA_MODE i .env och README.

Tangenter i kamerafönstret:  q = avsluta   p = integritetsläge   t = testlarm
"""

import argparse
import time

import cv2
import numpy as np

import config as cfg
from detector import FallDetector, extract_pose, is_lying, SKELETON
from notify import (send_alarm, send_info, call_phone, TelegramChat, handle_relative_message,
                    telegram_configured)
from camera import CameraGate
from routine import ActivityMonitor, CheckupSchedule, duration_text, print_routine

STATE_COLORS = {"OK": (0, 200, 0), "MÖJLIGT FALL": (0, 200, 255), "LIGGER KVAR": (0, 140, 255),
                "FRÅGAR": (255, 180, 0), "SVARADE OK": (180, 220, 0), "LARM": (0, 0, 255)}


# =====================================================================
# Bild
# =====================================================================

def draw(frame, pose, detector, monitor, t, privacy, fps):
    """Ritar streckgubbe och status. I integritetsläge visas bara streckgubben på svart."""
    h, w = frame.shape[:2]
    canvas = np.zeros_like(frame) if privacy else frame.copy()

    if pose is not None:
        danger = detector.state in ("LIGGER KVAR", "FRÅGAR", "LARM")
        color = (0, 0, 255) if danger else (0, 220, 0)
        pts = [(int(x * w), int(y * h)) for x, y in pose["kp"]]
        visible = lambda j: pose["conf"][j] > cfg.MIN_KP_CONF
        for a, b in SKELETON:
            if visible(a) and visible(b):
                cv2.line(canvas, pts[a], pts[b], color, 3)
        for j, p in enumerate(pts):
            if visible(j):
                cv2.circle(canvas, p, 4, (255, 255, 255), -1)

    cv2.rectangle(canvas, (0, 0), (w, 70), (30, 30, 30), -1)
    label = detector.state.replace("Ö", "O").replace("Å", "A")    # OpenCV kan inte rita å/ä/ö
    cv2.putText(canvas, label, (12, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, STATE_COLORS[detector.state], 3)

    info = f"fart {detector.speed:+.2f}"
    if pose is not None and pose["angle"] is not None:
        info += f"  vinkel {pose['angle']:.0f}"
    down = detector.seconds_down(t)
    if down:
        info += f"  nere {down:.0f}s"
    still = monitor.still_seconds(t)
    if still >= 60:
        info += f"  stilla {still / 60:.0f} min"
    info += f"  {fps:.0f} fps" + ("  [PRIVAT]" if privacy else "")
    cv2.putText(canvas, info, (max(w - 480, 300), 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)
    return canvas


def debug_line(detector, monitor, pose, t):
    still = f" | stilla {duration_text(monitor.still_seconds(t))}"
    if pose is None:
        return f"{detector.state:13s} | ingen person i bild" + still
    ang = f"{pose['angle']:3.0f}°" if pose["angle"] is not None else "  ?"
    return (f"{detector.state:13s} | fart {detector.speed:+.2f} (fall ≥ {cfg.DROP_SPEED}) | "
            f"vinkel {ang} (ligger ≥ {cfg.LYING_ANGLE}) | bredd/höjd {pose['aspect']:.2f} (ligger ≥ {cfg.LYING_ASPECT})"
            + still)


# =====================================================================
# Kamera
# =====================================================================

def open_camera(source, must_work=True):
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
    if not cap.isOpened():
        msg = (f"Kunde inte öppna kamera '{source}'. Prova --list-cameras, och kolla att "
               "VS Code har kameratillstånd (Systeminställningar > Integritet och säkerhet > Kamera).")
        if must_work:
            raise SystemExit(msg)
        print(f"  !! {msg}")
        return None
    return cap


def camera_off_view(gate, t):
    """Det som visas i fönstret när kameran är av."""
    canvas = np.zeros((360, 640, 3), np.uint8)
    for i, (text, size) in enumerate([("KAMERAN AR AV", 1.2), (ascii_text(gate.status(t)), 0.6),
                                      ("Lyssnar fortfarande efter rop pa hjalp", 0.6)]):
        cv2.putText(canvas, text, (20, 150 + 50 * i), cv2.FONT_HERSHEY_SIMPLEX, size, (200, 200, 200), 2 if i == 0 else 1)
    return canvas


def ascii_text(text):
    return text.translate(str.maketrans("åäöÅÄÖ–", "aaoAAO-"))       # OpenCV kan inte rita å/ä/ö


def list_cameras():
    print("Letar efter kameror...")
    for i in range(6):
        cap = cv2.VideoCapture(i)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        if ok:
            print(f"  --source {i}: {frame.shape[1]}x{frame.shape[0]}")
        cap.release()


# =====================================================================
# Start
# =====================================================================

def parse_args():
    ap = argparse.ArgumentParser(description="Fallvakt – fall-detektering med kamera")
    ap.add_argument("--source", default="0", help="Kameraindex (0, 1, ...) eller URL till videoström")
    ap.add_argument("--model", default="yolo11n-pose.pt", help="Pose-modell (laddas ner automatiskt)")
    ap.add_argument("--device", default=None, help="'mps' för Apple-GPU, annars CPU")
    ap.add_argument("--privacy", action="store_true", help="Visa och skicka bara streckgubbe")
    ap.add_argument("--debug", action="store_true", help="Skriv ut fart/vinkel/status två gånger per sekund")
    ap.add_argument("--no-voice", action="store_true", help="Stäng av röstkollen")
    ap.add_argument("--whisper-model", default=None, help="base / small / medium")
    ap.add_argument("--list-cameras", action="store_true")
    ap.add_argument("--test-alarm", action="store_true")
    ap.add_argument("--test-voice", action="store_true")
    ap.add_argument("--rutiner", action="store_true", help="Visa vad den har lärt sig om personens dygn")
    return ap.parse_args()


def start_voice(args):
    if args.no_voice:
        return None
    try:
        import faster_whisper, sounddevice  # noqa: F401
    except ImportError:
        print("Röstkollen är avstängd: kör  pip install -r requirements.txt")
        return None
    from voice import VoiceCheck
    return VoiceCheck(args.whisper_model)


def test_alarm(chat):
    send_alarm("Testlarm från Fallvakt – allt funkar! Tryck på en knapp eller skriv något.")
    call_phone("Det här är ett testsamtal från Fallvakt. Allt fungerar.")
    if chat:
        print("Väntar 60 s på svar i Telegram (tryck på en knapp eller skriv ett meddelande)...")
        time.sleep(60)
    else:
        time.sleep(10)


def test_voice(voice):
    voice.wait_until_ready()
    result, summary, last_line = voice.converse(1)
    if last_line:
        voice.say(last_line)
    print(f"\nResultat: {result}  –  {summary}")
    if result == "hjälp":
        print(f"Extra info till anhöriga: {voice.followup()}")


# =====================================================================
# Koller: inaktivitet och dagliga koller
# =====================================================================

INACTIVE_SITUATION = ("Kameran har inte sett personen röra sig på ovanligt länge. Du hör av dig för att "
                      "kolla att allt är bra – personen kanske bara vilar, sover eller läser.")
CHECKUP_SITUATION = ("Det här är en vanlig daglig koll, inget har hänt. Fråga vänligt hur personen mår idag. "
                     "Svarar hen att allt är bra är beslutet \"ok\".")


def inactivity_checkup(reason, voice, detector, monitor):
    """Stilla ovanligt länge: fråga först, larma bara om hen behöver hjälp eller inte svarar."""
    print(f"[KOLL] {reason}")
    if not voice:
        return detector.raise_alarm(f"{reason} (Röstkollen är avstängd.)")

    def on_result(result, summary):
        if result == "ok":
            monitor.mark_active(time.time())
            print(f"[KOLL] Allt bra: {summary}")
        elif result == "hjälp":
            detector.raise_alarm(f"{reason} Personen behöver hjälp. {summary}")
        else:
            detector.raise_alarm(f"{reason} Personen svarar inte – kan också vara att hen inte är hemma.")

    voice.check_up_in_background("Hej! Jag har inte sett dig röra dig på ett tag. Hur mår du?",
                                 INACTIVE_SITUATION, on_result,
                                 on_followup=lambda info: send_info(f"Mer info: {info}"))


def daily_checkup(hhmm, voice, detector, monitor, gate):
    """Daglig koll: anhöriga får ett lugnt besked. Bara "behöver hjälp" ger larm."""
    print(f"[KOLL] Daglig koll {hhmm}")

    def on_result(result, summary):
        if result == "ok":
            monitor.mark_active(time.time())
            send_info(f"☀️ Dagens koll {hhmm}: mår bra. {summary}")
        elif result == "hjälp":
            detector.raise_alarm(f"Dagens koll {hhmm}: personen behöver hjälp. {summary}")
        else:
            now = time.time()
            if gate.wake(now, "inget svar på dagens koll"):
                detector.suspect(now + cfg.WAKE_MINUTES * 60)
            send_info(f"Dagens koll {hhmm}: inget svar (kanske inte hemma). "
                      + ("Kameran startar en stund för att se efter." if gate.should_watch(now) else
                         "Kameran är pausad, så jag kan inte se efter."))

    voice.check_up_in_background("Hej! Det är dags för dagens koll. Hur mår du idag?",
                                 CHECKUP_SITUATION, on_result,
                                 on_followup=lambda info: send_info(f"Mer info: {info}"))


THUD_SITUATION = ("Mikrofonen hörde en smäll, men kameran kan inte se personen. Fråga om allt är bra – "
                  "det kan ha varit något som ramlade i golvet.")


def thud_checkup(voice, detector):
    """Hörde en smäll men kan inte se något: fråga med rösten. Inget svar = larm."""
    def on_result(result, summary):
        if result == "hjälp":
            detector.raise_alarm(f"Hörde en smäll. Personen behöver hjälp. {summary}")
        elif result != "ok":
            detector.raise_alarm("Hörde en smäll och personen svarar inte.")

    voice.check_up_in_background("Jag hörde en smäll. Är allt bra?", THUD_SITUATION, on_result,
                                 on_followup=lambda info: send_info(f"Mer info: {info}"))


def start_listening(voice, detector, gate):
    """Lyssnar efter rop på hjälp, smällar och "pausa kameran" / "slå på kameran"."""
    def on_call():
        gate.wake(time.time(), "rop på hjälp")

    def on_thud():
        now = time.time()
        if gate.paused(now):
            thud_checkup(voice, detector)            # personen har pausat kameran – fråga i stället för att titta
        elif gate.wake(now, "hörde en smäll", ask_if_unseen=True):
            detector.suspect(now + cfg.WAKE_MINUTES * 60)

    def on_command(cmd):
        now, hours = time.time(), cfg.MANUAL_HOURS
        if cmd == "paus":
            gate.pause(now)
            voice.say(f"Okej, kameran är avstängd i {hours} timmar. Jag hör dig fortfarande om du ropar på hjälp.")
            send_info(f"⏸ Personen pausade kameran i {hours} tim. Skriv /på för att slå på den.")
        else:
            gate.turn_on(now)
            voice.say("Okej, kameran är på.")
            send_info("▶️ Personen slog på kameran.")

    voice.listen_for_help_in_background(
        on_help=detector.call_for_help, on_followup=lambda info: send_info(f"Mer info: {info}"),
        on_call=on_call, on_thud=on_thud, on_command=on_command)


def main():
    args = parse_args()
    if args.list_cameras:
        return list_cameras()
    if args.rutiner:
        return print_routine()

    voice = start_voice(args)
    detector = FallDetector(use_voice=voice is not None)
    gate = CameraGate()
    chat = None
    if telegram_configured():
        chat = TelegramChat(lambda kind, text: handle_relative_message(kind, text, voice, detector, chat, gate))

    if args.test_alarm:
        return test_alarm(chat)
    if args.test_voice:
        return test_voice(voice) if voice else None

    if voice and cfg.ALWAYS_LISTEN:
        start_listening(voice, detector, gate)
    elif gate.mode == "vid_misstanke":
        print("OBS: 'vid_misstanke' behöver mikrofonen – utan röst startar kameran bara via /på i Telegram.")

    from ultralytics import YOLO
    print("Laddar kamera-AI (första gången laddas den ner, ~6 MB)...")
    model = YOLO(args.model)
    open_camera(args.source).release()          # kolla direkt att kameran går att öppna

    cap = None
    monitor = ActivityMonitor()
    schedule = CheckupSchedule() if voice else CheckupSchedule("")
    privacy = args.privacy
    last_t, fps, last_debug = time.time(), 0.0, 0.0
    print(f"Igång! q = avsluta, p = integritetsläge, t = testlarm  (röstkoll {'PÅ' if voice else 'AV'})")
    print(gate.status(time.time()))

    while True:
        t = time.time()
        if gate.should_watch(t, busy=detector.state != "OK"):
            if cap is None:
                cap = open_camera(args.source, must_work=False)
                if cap is not None:
                    print(f"[KAMERA] På – {gate.status(t)}")
                    monitor.resume(t)
        elif cap is not None:
            cap.release()
            cap = None
            print(f"[KAMERA] Av – {gate.status(t)}")

        pose = frame = None
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                print("Tappade kamerabilden, försöker igen...")
                time.sleep(0.5)
                continue
            fps = 0.9 * fps + 0.1 / max(t - last_t, 1e-6)
            pose = extract_pose(model(frame, verbose=False, device=args.device, classes=[0])[0])
            if pose is not None:
                gate.note_seen()
        else:
            time.sleep(0.2)
        last_t = t

        event = detector.update(t, pose)        # även med kameran av: larm från rösten ska gå iväg
        calm = detector.state == "OK" and not (voice and voice.busy_count)
        inactive = None
        if cap is not None:
            inactive = monitor.update(t, pose, lying=pose is not None and is_lying(pose),
                                      may_ask=cfg.INACTIVITY_CHECK and calm)
            view = draw(frame, pose, detector, monitor, t, privacy, fps)
        else:
            view = camera_off_view(gate, t)

        if args.debug and t - last_debug >= 0.5:
            last_debug = t
            print(debug_line(detector, monitor, pose, t) if cap is not None else gate.status(t))

        if inactive:
            inactivity_checkup(inactive, voice, detector, monitor)
        elif calm and voice and gate.unseen_wake_ended(t):
            thud_checkup(voice, detector)       # hörde en smäll men ingen syntes i bild
        elif calm:
            hhmm = schedule.due(t)
            if hhmm:
                daily_checkup(hhmm, voice, detector, monitor, gate)

        if event == "FRÅGA":
            print(f"[RÖST] Frågar hur personen mår (försök {detector.ask_attempt})")
            aid = detector.ask_id
            voice.ask_in_background(
                detector.ask_attempt,
                on_result=lambda res, summary, aid=aid: detector.give_voice_result(aid, res, summary),
                on_followup=lambda info: send_info(f"Mer info om fallet: {info}"))

        elif event == "LARM":
            jpg = None
            if frame is not None:
                photo = view if cfg.ALARM_IMAGE == "foto" else draw(frame, pose, detector, monitor, t, True, fps)
                ok_jpg, buf = cv2.imencode(".jpg", photo)
                jpg = buf.tobytes() if ok_jpg else None
            title = "Larm!" if detector.alarm_by_call else "Möjligt fall!"
            send_alarm(f"{title} {detector.alarm_reason} ({time.strftime('%H:%M:%S')})", jpg)
            call_phone(f"Larm från Fallvakt. {title} {detector.alarm_reason}")

        elif event == "RESTE SIG":
            send_info("✅ Personen har rest sig igen. Larmet är avslutat.")

        cv2.imshow("Fallvakt", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("p"):
            privacy = not privacy
        if key == ord("t"):
            send_alarm("Testlarm från Fallvakt")

    monitor.routine.save()
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

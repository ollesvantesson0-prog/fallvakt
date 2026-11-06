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

def open_camera(source):
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"Kunde inte öppna kamera '{source}'. Prova --list-cameras, och kolla att "
                         "VS Code har kameratillstånd (Systeminställningar > Integritet och säkerhet > Kamera).")
    return cap


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


def daily_checkup(hhmm, voice, detector, monitor):
    """Daglig koll: anhöriga får ett lugnt besked. Bara "behöver hjälp" ger larm."""
    print(f"[KOLL] Daglig koll {hhmm}")

    def on_result(result, summary):
        if result == "ok":
            monitor.mark_active(time.time())
            send_info(f"☀️ Dagens koll {hhmm}: mår bra. {summary}")
        elif result == "hjälp":
            detector.raise_alarm(f"Dagens koll {hhmm}: personen behöver hjälp. {summary}")
        else:
            send_info(f"Dagens koll {hhmm}: inget svar (kanske inte hemma). Inaktivitetskollen fortsätter vakta.")

    voice.check_up_in_background("Hej! Det är dags för dagens koll. Hur mår du idag?",
                                 CHECKUP_SITUATION, on_result,
                                 on_followup=lambda info: send_info(f"Mer info: {info}"))


def main():
    args = parse_args()
    if args.list_cameras:
        return list_cameras()
    if args.rutiner:
        return print_routine()

    voice = start_voice(args)
    detector = FallDetector(use_voice=voice is not None)
    chat = None
    if telegram_configured():
        chat = TelegramChat(lambda kind, text: handle_relative_message(kind, text, voice, detector, chat))

    if args.test_alarm:
        return test_alarm(chat)
    if args.test_voice:
        return test_voice(voice) if voice else None

    if voice and cfg.ALWAYS_LISTEN:
        voice.listen_for_help_in_background(
            on_help=detector.call_for_help,
            on_followup=lambda info: send_info(f"Mer info: {info}"))

    from ultralytics import YOLO
    print("Laddar kamera-AI (första gången laddas den ner, ~6 MB)...")
    model = YOLO(args.model)
    cap = open_camera(args.source)

    monitor = ActivityMonitor()
    schedule = CheckupSchedule() if voice else CheckupSchedule("")
    privacy = args.privacy
    last_t, fps, last_debug = time.time(), 0.0, 0.0
    print(f"Igång! q = avsluta, p = integritetsläge, t = testlarm  (röstkoll {'PÅ' if voice else 'AV'})")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Tappade kamerabilden, försöker igen...")
            time.sleep(0.5)
            continue

        t = time.time()
        fps = 0.9 * fps + 0.1 / max(t - last_t, 1e-6)
        last_t = t

        pose = extract_pose(model(frame, verbose=False, device=args.device, classes=[0])[0])
        event = detector.update(t, pose)
        calm = detector.state == "OK" and not (voice and voice.busy_count)
        inactive = monitor.update(t, pose, lying=pose is not None and is_lying(pose),
                                  may_ask=cfg.INACTIVITY_CHECK and calm)
        view = draw(frame, pose, detector, monitor, t, privacy, fps)

        if args.debug and t - last_debug >= 0.5:
            last_debug = t
            print(debug_line(detector, monitor, pose, t))

        if inactive:
            inactivity_checkup(inactive, voice, detector, monitor)
        elif calm:
            hhmm = schedule.due(t)
            if hhmm:
                daily_checkup(hhmm, voice, detector, monitor)

        if event == "FRÅGA":
            print(f"[RÖST] Frågar hur personen mår (försök {detector.ask_attempt})")
            aid = detector.ask_id
            voice.ask_in_background(
                detector.ask_attempt,
                on_result=lambda res, summary, aid=aid: detector.give_voice_result(aid, res, summary),
                on_followup=lambda info: send_info(f"Mer info om fallet: {info}"))

        elif event == "LARM":
            ok_jpg, jpg = cv2.imencode(".jpg", view)
            title = "Larm!" if detector.alarm_by_call else "Möjligt fall!"
            send_alarm(f"{title} {detector.alarm_reason} ({time.strftime('%H:%M:%S')})",
                       jpg.tobytes() if ok_jpg else None)
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
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

"""
SentinelX - person detection + DHT11 temperature -> buzzer control.

Laptop webcam -> YOLO11n (COCO class 0 = person) -> ALERT / CLEAR.
The ESP32 handles the DHT11 temperature alarm itself and reports readings back,
which are shown on the video window.
Runs on CPU by default; uses an NVIDIA GPU automatically if one is available.
If an ESP32 port is given, sends "ALERT\n" / "CLEAR\n" over USB serial.
Without --port it runs in test mode (status shown on screen only).

Install:
    python -m pip install ultralytics opencv-python pyserial

Run:
    python sentinelx.py                 # webcam + ESP32 buzzer on COM7
    python sentinelx.py --port none     # webcam only, test mode
    python sentinelx.py --source video.mp4

Press Q to quit.
"""

import argparse
import time

import cv2
import torch
from ultralytics import YOLO

PERSON_CLASS = 0


def parse_args():
    p = argparse.ArgumentParser(description="SentinelX person detector")
    p.add_argument("--source", default="0", help="camera index (0 = laptop webcam) or video file path")
    p.add_argument("--port", default="COM7", help="ESP32 serial port (use --port none for test mode)")
    p.add_argument("--model", default="yolo11n.pt", help="YOLO weights (downloaded automatically)")
    p.add_argument("--conf", type=float, default=0.5, help="minimum person confidence")
    p.add_argument("--imgsz", type=int, default=640, help="inference size; 480 or 320 is faster on slow CPUs")
    p.add_argument("--on-frames", type=int, default=3, help="consecutive person frames before buzzer ON")
    p.add_argument("--off-frames", type=int, default=10, help="consecutive empty frames before buzzer OFF")
    return p.parse_args()


def open_camera(source):
    if source.isdigit():
        # CAP_DSHOW opens Windows laptop webcams much faster than the default backend
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source {source!r}. Try --source 1 or check camera privacy settings.")
    return cap


def open_serial(port):
    if port is None or port.lower() == "none":
        print("[SentinelX] Test mode (no ESP32).")
        return None
    import serial

    try:
        esp = serial.Serial(port, 115200, timeout=0)
    except serial.SerialException as e:
        print(f"[SentinelX] Could not open {port} ({e}). Continuing in test mode.")
        return None
    time.sleep(2)  # ESP32 resets when the port opens; give it time to boot
    esp.reset_input_buffer()
    print(f"[SentinelX] Connected to ESP32 on {port}.")
    return esp


def send(esp, command):
    if esp is None:
        return
    try:
        esp.write((command + "\n").encode("utf-8"))
    except Exception as e:
        print(f"[SentinelX] Serial write failed: {e}")


def read_sensor(esp, buf, sensor):
    """Non-blocking read of 'TEMP 28.0 HUM 55 ALARM 0' lines sent by the ESP32."""
    if esp is None:
        return buf
    try:
        buf += esp.read(esp.in_waiting or 1).decode("utf-8", errors="ignore")
    except Exception:
        return buf
    *lines, buf = buf.split("\n")
    for line in lines:
        parts = line.split()
        if len(parts) == 6 and parts[0] == "TEMP":
            alarm = parts[5] == "1"
            if alarm != sensor["alarm"]:
                print(f"[SentinelX] TEMPERATURE {'HIGH -> SIREN ON' if alarm else 'NORMAL -> SIREN OFF'} ({parts[1]} C)")
            sensor.update(temp=float(parts[1]), hum=float(parts[3]), alarm=alarm, error=False)
            print(f"[{time.strftime('%H:%M:%S')}] TEMP {sensor['temp']:.1f} C  |  HUM {sensor['hum']:.0f}%"
                  f"{'  |  HIGH TEMP ALARM' if alarm else ''}")
        elif line.strip() == "DHT ERROR":
            sensor["error"] = True
            print(f"[{time.strftime('%H:%M:%S')}] DHT11 read error - check wiring")
    return buf


def main():
    args = parse_args()

    device = 0 if torch.cuda.is_available() else "cpu"
    print(f"[SentinelX] Inference device: {'GPU (CUDA)' if device == 0 else 'CPU'}")

    model = YOLO(args.model)
    cap = open_camera(args.source)
    esp = open_serial(args.port)

    buzzer_on = False
    seen, missed = 0, 0
    send(esp, "CLEAR")
    sensor = {"temp": None, "hum": None, "alarm": False, "error": False}
    serial_buf = ""

    prev = time.time()
    fps = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[SentinelX] No more frames.")
                break

            results = model.predict(
                frame,
                classes=[PERSON_CLASS],
                conf=args.conf,
                imgsz=args.imgsz,
                device=device,
                verbose=False,
            )
            person_count = len(results[0].boxes)

            # Debounce so a single missed/false frame doesn't flicker the buzzer
            if person_count > 0:
                seen, missed = seen + 1, 0
            else:
                seen, missed = 0, missed + 1

            if not buzzer_on and seen >= args.on_frames:
                buzzer_on = True
                send(esp, "ALERT")
                print(f"[SentinelX] PERSON DETECTED -> BUZZER ON ({person_count})")
            elif buzzer_on and missed >= args.off_frames:
                buzzer_on = False
                send(esp, "CLEAR")
                print("[SentinelX] NO PERSON -> BUZZER OFF")

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev, 1e-6))
            prev = now

            annotated = results[0].plot()
            status = f"PERSON x{person_count} - BUZZER ON" if buzzer_on else "NO PERSON - BUZZER OFF"
            color = (0, 0, 255) if buzzer_on else (0, 200, 0)
            cv2.putText(annotated, status, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(annotated, f"FPS {fps:.1f}  |  {'ESP32 ' + args.port if esp else 'TEST MODE'}",
                        (15, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

            serial_buf = read_sensor(esp, serial_buf, sensor)
            if sensor["error"]:
                temp_text, temp_color = "DHT11 ERROR - check wiring", (0, 165, 255)
            elif sensor["temp"] is None:
                temp_text, temp_color = "TEMP --", (255, 255, 255)
            else:
                temp_text = f"TEMP {sensor['temp']:.1f} C  HUM {sensor['hum']:.0f}%"
                if sensor["alarm"]:
                    temp_text += "  - HIGH TEMP SIREN"
                temp_color = (0, 0, 255) if sensor["alarm"] else (0, 200, 0)
            # Dark background strip so the reading stays readable over any scene
            (tw, th), _ = cv2.getTextSize(temp_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(annotated, (10, 78), (20 + tw, 88 + th), (0, 0, 0), -1)
            cv2.putText(annotated, temp_text, (15, 83 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.7, temp_color, 2)

            cv2.imshow("SentinelX", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        send(esp, "CLEAR")  # always leave the buzzer off
        if esp is not None:
            esp.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

# SentinelX

A person-detection and temperature alarm. A laptop webcam runs YOLO11 to detect people, and an ESP32 drives a buzzer and a red LED. A DHT11 sensor on the ESP32 adds a high-temperature alarm.

| Event | Buzzer | Red LED |
|---|---|---|
| Person in camera frame | Steady buzz | Solid on |
| Temperature ≥ 35 °C | Two-tone siren | Blinking |
| Both at once | Two-tone siren (temperature has priority) | Blinking |
| Neither | Off | Off |

## How it works

```
Laptop webcam ──> YOLO11n (Python, CPU or GPU) ──USB serial──> ESP32 ──> Buzzer + red LED
                                                                  ^
                                                    DHT11 ────────┘ (temperature, read by the ESP32)
```

- **Python script ([sentinelx.py](sentinelx.py)):** runs YOLO11n on each webcam frame and looks only for the COCO `person` class. It ignores chairs, bags and every other object. When a person appears or leaves, it sends `ALERT` or `CLEAR` to the ESP32. It also shows the live temperature from the ESP32 on the video window and in the terminal.
- **ESP32 firmware ([firmware/sentinelx_esp32/sentinelx_esp32.ino](firmware/sentinelx_esp32/sentinelx_esp32.ino)):** reads the DHT11 every 2 seconds and checks the temperature itself, so the temperature alarm works even if the laptop is disconnected. It drives the buzzer and LED, and reports each reading back as `TEMP 28.0 HUM 55 ALARM 0`.
- **No training needed:** the pretrained YOLO11n weights (about 5.4 MB) download automatically on the first run.
- **Debounce:** the buzzer turns on after 3 frames in a row with a person, and off after 10 frames in a row without one. This stops a single missed or false frame from flickering it.

## Hardware

- ESP32 DevKit (ESP32 Dev Module)
- 3-pin buzzer module (GND / VCC / I/O). The firmware drives it with a tone, so passive buzzer modules work too.
- DHT11 temperature and humidity sensor (3-pin module)
- Red LED and a 220–330 Ω resistor
- USB cable from the ESP32 to the laptop

### Wiring

| Component | Component pin | ESP32 pin |
|---|---|---|
| Buzzer | VCC | 3V3 |
| Buzzer | GND | GND |
| Buzzer | I/O | GPIO25 |
| DHT11 | VCC (+) | 3V3 (use VIN/5V if readings are wrong) |
| DHT11 | GND (−) | GND |
| DHT11 | DATA / OUT | GPIO27 |
| Red LED | Long leg (+) | GPIO26, through a 220–330 Ω resistor |
| Red LED | Short leg (−) | GND |

```
ESP32 GPIO25 ──────────────────── Buzzer I/O
ESP32 GPIO27 ──────────────────── DHT11 DATA
ESP32 GPIO26 ──[ 220–330 Ω ]───── LED (+)   LED (−) ── GND
ESP32 3V3 ─────────────────────── Buzzer VCC, DHT11 VCC
ESP32 GND ─────────────────────── Buzzer GND, DHT11 GND, LED (−)
```

Avoid GPIO 0, 2, 5, 12 and 15, which affect booting; GPIO 6–11, which the flash uses; GPIO 34–39, which are input only; and GPIO 1 and 3, the USB serial lines.

## Setup

### 1. Flash the ESP32

1. Install the [Arduino IDE](https://www.arduino.cc/en/software), then install the **esp32 by Espressif Systems** board package (version 3.x) from Boards Manager.
2. In Library Manager, install **DHT sensor library for ESPx** by beegee_tokyo.
3. Open `firmware/sentinelx_esp32/sentinelx_esp32.ino`, select the **ESP32 Dev Module** board and your COM port, and click Upload.
4. Open Serial Monitor at **115200** baud. You should see `SentinelX ESP32 Ready`, followed by a `TEMP ... HUM ...` line every 2 seconds. To test the buzzer, type `ALERT` and then `CLEAR`, with the line ending set to Newline.
5. **Close Serial Monitor before running the Python script.** Only one program can use the COM port at a time.

### 2. Set up Python

Python 3.10 or newer is required.

```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Linux / macOS

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The default `pip install` on Windows gives the CPU build of PyTorch. To keep the install small, or if pip runs out of memory, install the CPU build of PyTorch on its own first:

```bash
python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install --no-cache-dir -r requirements.txt
```

### 3. Run

```bash
python sentinelx.py                     # webcam + ESP32 on COM7
python sentinelx.py --port COM5         # a different COM port
python sentinelx.py --port none         # webcam only, no ESP32 (test mode)
python sentinelx.py --source video.mp4  # use a video file instead of the webcam
```

Press **Q** in the video window to quit. The buzzer is always switched off on exit.

To find your COM port, open Windows Device Manager → Ports (COM & LPT).

## Options

| Option | Default | Description |
|---|---|---|
| `--source` | `0` | Camera index (`0` = built-in webcam) or video file path |
| `--port` | `COM7` | ESP32 serial port, or `none` for test mode |
| `--model` | `yolo11n.pt` | YOLO weights file |
| `--conf` | `0.5` | Minimum confidence for a person detection |
| `--imgsz` | `640` | Inference size; `480` or `320` is faster on slow CPUs |
| `--on-frames` | `3` | Frames in a row with a person before the buzzer turns on |
| `--off-frames` | `10` | Frames in a row without a person before the buzzer turns off |

To change the temperature limit, edit `TEMP_LIMIT` (alarm on) and `TEMP_RESET` (alarm off) at the top of the firmware. Keep `TEMP_RESET` about 1 °C lower so the alarm doesn't flicker at the limit.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not open COM7 ... Access is denied` | Another program is using the port, usually the Arduino Serial Monitor. Close it, or unplug and replug the ESP32. |
| Camera doesn't open | Try `--source 1`, and check Windows Settings → Privacy → Camera. |
| Buzzer only chirps | The firmware already drives the buzzer with `tone()`. Make sure the latest firmware is uploaded. |
| Buzzer is very quiet | Move the buzzer's VCC from 3V3 to VIN (5V). |
| LED doesn't light | The LED is probably in backwards. The long leg goes to the resistor and GPIO26. |
| Video shows `DHT11 ERROR - check wiring` | The ESP32 got an unrealistic reading and ignored it. Check that DATA is on GPIO27, use short wires, and try powering the DHT11 from VIN (5V). If readings stay wrong, replace the sensor. |
| Low FPS | Use `--imgsz 480` or `--imgsz 320`. |
| `MemoryError` during `pip install` | Close other apps, install with `--no-cache-dir`, and make sure the Windows page file is enabled. |

## Project structure

```
sentinelx.py                               Python: webcam + YOLO person detection + serial link
requirements.txt                           Python dependencies
firmware/sentinelx_esp32/sentinelx_esp32.ino   ESP32: buzzer, LED, DHT11 alarm
```

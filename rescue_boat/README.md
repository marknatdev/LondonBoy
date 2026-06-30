# 🚤 Autonomous Rescue Boat

An autonomous rescue boat system powered by YOLO object detection and Arduino hardware control. Everything runs on a single device — the Arduino UNO Q.

---

## Architecture

The system is self-contained on the boat. An operator connects remotely via any web browser over WiFi.

```
┌─────────────────────────────────────────────────────┐
│              Arduino UNO Q (Boat)                   │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │  Linux MPU (Docker Container)                 │  │
│  │                                               │  │
│  │  • YOLO26n person detection (ONNX Runtime)    │  │
│  │  • FastAPI + SocketIO server (port 8080)      │  │
│  │  • Apple-inspired operator dashboard          │  │
│  │  • Serial bridge to Arduino MCU               │  │
│  └─────────────────────┬─────────────────────────┘  │
│                        │ USB Serial (JSON)           │
│  ┌─────────────────────▼─────────────────────────┐  │
│  │  Arduino MCU                                  │  │
│  │                                               │  │
│  │  • Steering Servo (D9)                        │  │
│  │  • Supply Drop Servo (D10)                    │  │
│  │  • HL-51 Relay → DC Motor (D4)               │  │
│  │  • Modulino Distance (safety cutoff)          │  │
│  │  • Modulino Pixels (status LEDs)              │  │
│  │  • Modulino Buttons (manual override)         │  │
│  │  • Modulino Movement (IMU)                    │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
          │
          │  WiFi (port 8080)
          ▼
   ┌──────────────┐
   │  Any Browser  │  ← Operator opens http://<boat-ip>:8080
   └──────────────┘
```

---

## Project Structure

```
rescue_boat/
│
├── boat/
│   ├── docker-compose.yml         ← Single container deployment
│   ├── models/
│   │   └── yolo26n.onnx           ← Pre-trained ONNX model
│   ├── vision/
│   │   ├── detector.py            ← Detection + API + Dashboard server
│   │   └── requirements.txt
│   ├── dashboard/
│   │   ├── index.html             ← Apple-inspired dark mode UI
│   │   ├── style.css              ← Glassmorphism & system colors
│   │   └── dashboard.js           ← SocketIO + WebSocket video client
│   ├── arduino_firmware/
│   │   └── rescue_boat_firmware.ino
│   └── wiring.md                  ← Hardware connection guide
│
└── README.md
```

---

## Quickstart

### 1. Flash the Arduino

1. Follow the wiring in [`boat/wiring.md`](boat/wiring.md).
2. Open `boat/arduino_firmware/rescue_boat_firmware.ino` in Arduino IDE.
3. Install libraries: **ArduinoJson** and **Arduino_Modulino**.
4. Flash the code.

### 2. Start Docker on the Boat

```bash
cd rescue_boat/boat
docker compose up -d
```

### 3. Open the Dashboard

From any device on the same WiFi, open:

```
http://<boat-ip>:8080
```

---

## How It Works

1. **Detect**: YOLO26n finds persons in the camera frame via ONNX Runtime.
2. **Track**: The highest-confidence person's X-position maps to a steering angle (0–180°).
3. **Drop**: When the target crosses the ROI danger zone (lower 60% of frame), the supply drop servo activates.
4. **Safety**: The Modulino Distance sensor cuts the DC motor if an obstacle is within 20 cm — regardless of vision commands.

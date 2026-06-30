# 🚤 Autonomous Rescue Boat

An autonomous rescue boat with person detection and supply drop capabilities. The system is split across two devices connected over WiFi.

---

## Architecture

```
┌──────────────────────────────────┐        WiFi         ┌──────────────────────────────────┐
│     Arduino UNO Q (Boat)         │                     │         Operator PC              │
│                                  │                     │                                  │
│  Docker: relay_server.py         │  raw JPEG frames    │  Docker: detector.py             │
│  • Capture USB webcam            │ ──────────────────► │  • YOLO26n inference (ONNX)      │
│  • Stream via WebSocket /ws      │                     │  • Annotate & track persons      │
│  • Accept serial commands        │  serial commands    │  • Serve Apple dashboard         │
│  • Forward JSON to Arduino MCU   │ ◄────────────────── │  • SocketIO detection events     │
│                                  │  POST /api/serial   │  • Send commands to boat         │
│  Port 5000                       │                     │  Port 8080                       │
├──────────────────────────────────┤                     └──────────────────────────────────┘
│  Arduino MCU (Firmware)          │                               │
│  • Steering Servo (D9)           │                               ▼
│  • Supply Drop Servo (D10)       │                     ┌──────────────────┐
│  • HL-51 Relay → DC Motor (D4)   │                     │   Any Browser    │
│  • Modulino Distance / Pixels    │                     │  localhost:8080  │
│  • Modulino Buttons / Movement   │                     └──────────────────┘
└──────────────────────────────────┘
```

---

## Project Structure

```
rescue_boat/
│
├── boat/                              ← Deploy on Arduino UNO Q
│   ├── docker-compose.yml             ← Lightweight camera relay (port 5000)
│   ├── vision/
│   │   └── relay_server.py            ← Stream camera + forward serial
│   ├── arduino_firmware/
│   │   └── rescue_boat_firmware.ino   ← Flash to Arduino MCU
│   └── wiring.md                      ← Hardware connection guide
│
├── pc/                                ← Deploy on Operator PC
│   ├── docker-compose.yml             ← Detection + dashboard (port 8080)
│   ├── models/
│   │   └── yolo26n.onnx               ← ONNX model (runs on PC)
│   ├── vision/
│   │   ├── detector.py                ← YOLO inference + dashboard server
│   │   └── requirements.txt
│   └── dashboard/
│       ├── index.html                 ← Apple-inspired dark mode UI
│       ├── style.css
│       └── dashboard.js
│
└── README.md
```

---

## Quickstart

### 1. Flash the Arduino MCU

1. Follow the wiring in [`boat/wiring.md`](boat/wiring.md).
2. Open `boat/arduino_firmware/rescue_boat_firmware.ino` in Arduino IDE.
3. Install libraries: **ArduinoJson** and **Arduino_Modulino**.
4. Flash the code.

### 2. Start the Boat Relay

SSH into the Arduino UNO Q and run:

```bash
cd rescue_boat/boat
docker compose up -d
```

This starts the lightweight camera relay on **port 5000**.

### 3. Start the PC (Detection + Dashboard)

On the operator PC, set the boat's WiFi IP and run:

```bash
cd rescue_boat/pc

# Edit docker-compose.yml → set BOAT_IP to the boat's IP address
docker compose up -d
```

### 4. Open Dashboard

Open `http://localhost:8080` in any browser.

---

## How It Works

1. **Boat streams** raw camera frames over WebSocket to the PC in real-time.
2. **PC runs YOLO26n** on each frame, detects persons, and calculates steering.
3. **PC sends commands** (`steering`, `drop`, `motor`) back to the boat via HTTP.
4. **Boat forwards** commands to the Arduino MCU over USB Serial (JSON).
5. **Arduino MCU** actuates servos, relay, and Modulino modules.
6. **Safety**: Modulino Distance sensor cuts the motor if an obstacle is within 20 cm — regardless of PC commands.

# 🚤 Autonomous Rescue Boat — System Overview

This project is split into two independent deployments connected over **WiFi**.

---

## Architecture

```
┌──────────────────────────────────┐        WiFi        ┌──────────────────────────┐
│       Arduino UNO Q (Boat)       │ ◄────────────────► │     Operator PC          │
│                                  │                    │                          │
│  ┌─────────────────────────────┐ │  MJPEG video       │  ┌──────────────────┐   │
│  │  Linux MPU (Qualcomm)       │ │ ──────────────────►│  │ Dashboard Server │   │
│  │  • YOLO26n detection        │ │  REST commands     │  │ (Flask, port 8080│   │
│  │  • ROI danger-zone logic    │ │ ◄──────────────────│  └────────┬─────────┘   │
│  │  • Boat API (port 5000)     │ │  WebSocket events  │           │             │
│  │  • Mode Manager             │ │ ──────────────────►│  ┌────────▼─────────┐   │
│  │  • Serial Bridge            │ │                    │  │  Browser (UI)    │   │
│  └─────────────────────────────┘ │                    │  └──────────────────┘   │
│  ┌─────────────────────────────┐ │                    └──────────────────────────┘
│  │  STM32 MCU (Zephyr OS)      │ │
│  │  • Steering Servo (D9)      │ │
│  │  • Supply Servo (D10)       │ │
│  │  • DC Motor (D4/D5)         │ │
│  └─────────────────────────────┘ │
└──────────────────────────────────┘
```

---

## What Runs Where

| Responsibility | Arduino UNO Q (Boat) | Operator PC |
|---|---|---|
| Camera capture | ✅ USB Webcam | ❌ |
| YOLO26n inference | ✅ Qualcomm MPU | ❌ |
| ROI danger-zone logic | ✅ | ❌ |
| Motor / servo control | ✅ STM32 MCU | ❌ |
| Boat API server | ✅ Port 5000 | ❌ |
| Dashboard web server | ❌ | ✅ Port 8080 |
| Web browser (UI) | ❌ | ✅ |
| SocketIO real-time feed | ✅ broadcasts | ✅ receives |

---

## Project Structure

```
rescue_boat/
│
├── boat/                      ← Deploy on Arduino UNO Q
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── vision/
│   │   ├── detector.py        ← YOLO26n + ROI logic
│   │   ├── roi_config.py
│   │   └── requirements.txt
│   ├── server/
│   │   ├── boat_app.py        ← Lightweight API-only Flask server
│   │   ├── mode_manager.py    ← Scout/Rescue/Supply Drop state machine
│   │   └── serial_bridge.py   ← UART to STM32 MCU
│   └── arduino_firmware/
│       └── rescue_boat_firmware.ino
│
└── pc/                        ← Deploy on Operator PC
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    ├── server/
    │   └── pc_app.py          ← Dashboard server + API proxy
    └── dashboard/
        ├── index.html
        ├── style.css
        └── dashboard.js
```

---

## Quickstart

### Step 1 — Deploy on the Boat (Arduino UNO Q)

```bash
# Copy the boat/ folder to the Arduino UNO Q via SSH or USB
scp -r boat/ user@<boat-ip>:~/rescue_boat/

# SSH into the boat
ssh user@<boat-ip>

# Build and run
cd ~/rescue_boat/boat
docker compose up -d

# Verify the API is running
curl http://localhost:5000/api/ping
# → {"ok": true, "component": "boat"}
```

### Step 2 — Deploy on the Operator PC

```bash
cd pc/

# Set the boat's IP address (find it with: ssh into boat, run `ip addr`)
# Edit docker-compose.yml and change BOAT_IP=192.168.1.xxx

docker compose up -d

# Open dashboard in browser
# → http://localhost:8080
```

### Step 3 — Flash the Arduino MCU

1. Open `boat/arduino_firmware/rescue_boat_firmware.ino` in Arduino IDE
2. Install library: **ArduinoJson** v7+ (by Benoit Blanchon)
3. Select board: Arduino UNO Q (STM32 MCU side)
4. Upload

---

## Environment Variables

### Boat (`boat/docker-compose.yml`)

| Variable | Default | Description |
|---|---|---|
| `CAMERA_INDEX` | `0` | OpenCV camera device index |
| `SERIAL_PORT` | `/dev/ttyACM0` | UART to STM32 MCU |
| `SERIAL_BAUD` | `9600` | UART baud rate |
| `ROI_LINE_PERCENT` | `60` | ROI line height (% from top) |
| `PORT` | `5000` | API server port |
| `CORS_ORIGINS` | `*` | Allow PC dashboard (set to PC IP for security) |

### PC (`pc/docker-compose.yml`)

| Variable | Default | Description |
|---|---|---|
| `BOAT_IP` | `192.168.1.100` | **Set this to your boat's WiFi IP** |
| `BOAT_PORT` | `5000` | Boat API port |
| `PORT` | `8080` | PC dashboard port |

---

## Communication Protocol

All communication between PC and Boat goes over **HTTP + WebSocket** on port 5000.

| Direction | Protocol | Data |
|---|---|---|
| Boat → PC | MJPEG HTTP stream | Camera + YOLO annotations |
| PC → Boat | HTTP POST | Mode change, target coords, drop command |
| Boat → PC | WebSocket (SocketIO) | Detection events, status updates |

---

## Wiring

See [boat/wiring_diagram.md](boat/wiring_diagram.md) for full hardware connections.

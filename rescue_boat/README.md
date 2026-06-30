# 🚤 Autonomous Rescue Boat — System Overview

This project is an autonomous rescue boat system that uses computer vision (YOLO) and an Arduino-based hardware control system.

---

## Architecture

The system consists of three main hardware layers:

1. **Linux Vision & Server (Boat)**
   - Runs `detector.py` using ONNX Runtime for lightweight YOLO person detection.
   - Hosts a FastAPI server providing real-time WebSockets and an HTTP dashboard.
   - Calculates steering and drop commands and sends them via USB Serial to the MCU.

2. **Arduino MCU (Boat Hardware Controller)**
   - Runs `rescue_boat_firmware.ino` (Compatible with Arduino UNO R4 / UNO Q).
   - **Modulino Ecosystem (I2C Qwiic)**:
     - *Modulino Distance*: Acts as a safety cutoff (stops motor if obstacle < 20cm).
     - *Modulino Pixels*: Provides visual status (Green = tracking, Red = obstacle, Blue = dropping).
     - *Modulino Movement & Buttons*: Used for overrides and orientation tracking.
   - **Servos**: Steering Servo (D9) and Supply Drop Servo (D10).
   - **Relay**: HL-51 Active-High Relay (D4) controlling the main DC motor.

3. **Operator PC**
   - Accesses the boat's dashboard remotely via a web browser.
   - Features a clean, Apple-inspired premium dark mode UI with live camera feed, tracking stats, and operator controls.

---

## Project Structure

```
rescue_boat/
│
├── boat/                      ← Deploy on the Linux MPU (Boat)
│   ├── Dockerfile
│   ├── docker-compose.yml     ← Runs the vision system (host network, privileged)
│   ├── models/
│   │   └── yolo26n.onnx       ← Pre-trained ONNX model
│   ├── vision/
│   │   ├── detector.py        ← YOLO inference, FastAPI server, and PySerial bridge
│   │   └── requirements.txt
│   ├── arduino_firmware/
│   │   └── rescue_boat_firmware.ino  ← Flash to the Arduino MCU
│   └── wiring.md              ← Hardware connection guide
│
└── pc/                        ← Operator UI
    └── dashboard/
        ├── index.html         ← Apple-inspired layout
        ├── style.css          ← Glassmorphism & System Colors
        └── dashboard.js       ← SocketIO connection logic
```

---

## Quickstart

### Step 1 — Flash the Arduino MCU

1. Follow the wiring instructions in `boat/wiring.md`.
2. Open `boat/arduino_firmware/rescue_boat_firmware.ino` in the Arduino IDE.
3. Install required libraries: **ArduinoJson** and **Arduino_Modulino**.
4. Flash the code to the Arduino.

### Step 2 — Deploy the Vision System (Linux MPU)

SSH into the boat's Linux environment and run:

```bash
cd rescue_boat/boat
docker compose up -d
```

*This spins up the ONNX vision pipeline, connects to `/dev/video0` and `/dev/ttyACM0`, and starts the server on port 8080.*

### Step 3 — Operator PC Dashboard

To view the newly redesigned Apple-inspired dashboard, you can open the `pc/dashboard/index.html` file in a browser, or serve it locally, and it will connect to the boat's WebSocket stream.

Alternatively, if you hit the boat's IP directly at `http://<boat-ip>:8080`, it will serve the built-in minimal dashboard.

---

## System Logic

1. **Scout & Track**: The vision system uses YOLO26n to detect `Person` classes. It finds the highest confidence person and maps their relative X coordinate to a 0-180 degree steering angle.
2. **Follow**: The Arduino receives the steering angle via JSON over PySerial and adjusts the Steering Servo. The Relay (DC Motor) is engaged.
3. **Danger Zone & Drop**: If the tracked person enters the lower 60% of the camera frame (the ROI line), the system identifies them as "in danger" and triggers the Supply Drop Servo.
4. **Safety Override**: Regardless of vision commands, if the Modulino Distance sensor detects an obstacle within 20cm, it cuts power to the Relay (DC Motor) to prevent collisions.

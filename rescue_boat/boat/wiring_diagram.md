# Autonomous Rescue Boat — Wiring Diagram

## Hardware Overview

```
┌──────────────────────────────────────────────────────────┐
│                  Arduino UNO Q                           │
│                                                          │
│  Linux MPU (Qualcomm)          STM32 MCU (Zephyr)       │
│  ┌─────────────────────┐       ┌──────────────────────┐ │
│  │ Python + YOLO26n    │ UART  │ Arduino Sketch       │ │
│  │ Flask Web Server    │──────►│ D9  → Steer Servo    │ │
│  │ Mode Manager        │       │ D10 → Supply Servo   │ │
│  └─────────────────────┘       │ D5  → Motor PWM      │ │
│  USB Port ────► Webcam         │ D4  → Motor DIR      │ │
│                                └──────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## Pin Connections Table

| Component | Arduino Pin | Wire Color (suggested) | Notes |
|-----------|-------------|----------------------|-------|
| Steering Servo — Signal | **D9** | Yellow | PWM signal line |
| Steering Servo — VCC | 5V | Red | Regulated 5V |
| Steering Servo — GND | GND | Black | Common ground |
| Supply Drop Servo — Signal | **D10** | Orange | PWM signal line |
| Supply Drop Servo — VCC | 5V | Red | Regulated 5V |
| Supply Drop Servo — GND | GND | Black | Common ground |
| DC Motor — PWM (speed) | **D5** | Blue | Via L298N IN1/ENA |
| DC Motor — DIR (direction) | **D4** | Green | Via L298N IN2 |
| USB Webcam | USB Host Port | — | Camera index 0 |

---

## L298N Motor Driver Connections

```
Battery (7.4V LiPo)
    │
    ├── (+) ──────► L298N VIN
    └── (-) ──────► L298N GND ──────► Arduino GND

L298N
    ├── ENA ──────────────────────────► Arduino D5 (PWM)
    ├── IN1 ──────────────────────────► Arduino D4 (DIR)
    ├── IN2 ──────────────────────────► GND (fixed)
    ├── OUT1 ─────────────────────────► DC Motor (+)
    ├── OUT2 ─────────────────────────► DC Motor (-)
    └── 5V  ─────── (optional) ───────► Arduino VIN (if no separate supply)
```

> **Note:** The L298N's onboard 5V regulator can power the Arduino if you
> enable the 5V jumper and your battery voltage is 7–12V.

---

## Servo Wiring Detail

```
Steering Servo (D9)         Supply Servo (D10)
┌─────────────┐             ┌─────────────┐
│  Signal ────┼─────► D9   │  Signal ────┼─────► D10
│  VCC    ────┼─────► 5V   │  VCC    ────┼─────► 5V
│  GND    ────┼─────► GND  │  GND    ────┼─────► GND
└─────────────┘             └─────────────┘
```

> **Note:** If running two servos simultaneously, use an external 5V BEC
> (Battery Eliminator Circuit) rather than the Arduino's onboard 5V pin
> to avoid brownouts.

---

## Servo Angle Reference

| Action | Steering Servo (D9) | Supply Servo (D10) |
|--------|--------------------|--------------------|
| Full Left | 50° | — |
| Straight Ahead | 90° (neutral) | — |
| Full Right | 130° | — |
| Supply Closed | — | 0° |
| Supply Open (Drop) | — | 90° |

---

## Power Budget (Prototype)

| Component | Voltage | Max Current |
|-----------|---------|-------------|
| Arduino UNO Q (Linux MPU) | 5V USB or 7–12V VIN | ~2A |
| Steering Servo | 5V | ~500mA peak |
| Supply Servo | 5V | ~500mA peak |
| DC Motor (via L298N) | 7.4V | ~1–2A |
| USB Webcam | 5V (USB) | ~500mA |

**Recommended battery:** 7.4V 2200mAh 2S LiPo with 20C+ rating.

---

## Serial Port Reference

| Platform | Default Port |
|----------|-------------|
| Arduino UNO Q (Linux → STM32) | `/dev/ttyS0` or `/dev/ttyACM0` |
| Raspberry Pi | `/dev/ttyAMA0` |
| Linux laptop (USB-Serial) | `/dev/ttyUSB0` |

Set the port via the `SERIAL_PORT` environment variable in `docker-compose.yml`.

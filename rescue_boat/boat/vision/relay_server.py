"""
relay_server.py — Lightweight boat relay server (Arduino UNO Q)

Responsibilities:
  • Capture webcam frames and stream them over WebSocket /ws (real-time)
  • Accept serial commands via POST /api/serial and forward to Arduino MCU
  • Health check via GET /api/ping

No YOLO inference runs here — that is offloaded to the PC.
"""

import asyncio
import json
import os

import cv2
import serial
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse

# ── Configuration ─────────────────────────────────────────────────────────────
CAMERA_ID   = int(os.environ.get("CAMERA_ID", 0))
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "9600"))

app = FastAPI()

# ── Serial Connection ─────────────────────────────────────────────────────────
try:
    arduino = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
    serial_dry_run = False
    print(f"[serial] Connected to Arduino on {SERIAL_PORT}")
except Exception as e:
    arduino = None
    serial_dry_run = True
    print(f"[serial] DRY-RUN mode — {e}")


def send_to_arduino(steering: int, drop: int, motor: int):
    if arduino and arduino.is_open:
        payload = json.dumps({
            "steering": steering,
            "drop": drop,
            "motor": motor,
        }) + "\n"
        try:
            arduino.write(payload.encode("utf-8"))
        except Exception as e:
            print(f"[serial] Write failed: {e}")


# ── Camera ────────────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


# ── WebSocket: Stream raw camera frames ──────────────────────────────────────
@app.websocket("/ws")
async def camera_stream(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_event_loop()
    try:
        while True:
            ok, frame = await loop.run_in_executor(None, cap.read)
            if not ok:
                await asyncio.sleep(0.1)
                continue
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            await ws.send_bytes(buf.tobytes())
            await asyncio.sleep(0.01)  # ~100 FPS cap
    except Exception:
        pass


# ── REST API: Receive serial commands from PC ─────────────────────────────────
@app.post("/api/serial")
async def api_serial(request: Request):
    data = await request.json()
    steering = data.get("steering", 90)
    drop = data.get("drop", 0)
    motor = data.get("motor", 0)
    send_to_arduino(steering=steering, drop=drop, motor=motor)
    return {"ok": True, "sent": {"steering": steering, "drop": drop, "motor": motor}}


@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "component": "boat", "serial_dry_run": serial_dry_run}


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

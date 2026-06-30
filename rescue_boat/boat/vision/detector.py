import asyncio
import logging
import os
import time
import json
import cv2
import numpy as np
import yaml
import onnxruntime as ort
import serial
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

logging.getLogger("websockets").setLevel(logging.CRITICAL)
ort.set_default_logger_severity(3)

# ── Configuration ─────────────────────────────────────────────────────────────
CAMERA_ID   = int(os.environ.get("CAMERA_ID", 0))
MODEL_PATH  = os.environ.get("MODEL_PATH", "/app/model.onnx")
LABELS_PATH = os.environ.get("LABELS_PATH", "/app/coco8.yml")
CONF_THRESH = float(os.environ.get("CONF_THRESH", "0.45"))
INPUT_W     = int(os.environ.get("INPUT_W", "640"))
INPUT_H     = int(os.environ.get("INPUT_H", "640"))
ROI_PERCENT = float(os.environ.get("ROI_PERCENT", "60"))

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "9600"))

app = FastAPI()

# ── Serial Connection ─────────────────────────────────────────────────────────
try:
    arduino = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
    print(f"[serial] Connected to Arduino on {SERIAL_PORT}")
except Exception as e:
    arduino = None
    print(f"[serial] Failed to connect to {SERIAL_PORT}: {e}")

def send_to_arduino(steering: int, drop: int, motor: int):
    if arduino and arduino.is_open:
        payload = json.dumps({
            "steering": steering,
            "drop": drop,
            "motor": motor
        }) + "\n"
        try:
            arduino.write(payload.encode('utf-8'))
        except Exception as e:
            print(f"[serial] Write failed: {e}")

# ── UI Dashboard (from WORKSHOP6) ─────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Rescue Boat Vision</title>
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #0a0a0f; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; font-family: 'Segoe UI', sans-serif; color: #e0e0e0; padding: 24px; gap: 20px;}
    .card { background: #13131a; border: 1px solid #1e1e2e; border-radius: 16px; overflow: hidden; box-shadow: 0 8px 40px rgba(0,0,0,0.6); max-width: 900px; width: 100%; }
    .video-wrap { position: relative; background: #08080d; aspect-ratio: 16/9; display: flex; align-items: center; justify-content: center; }
    #feed { width: 100%; height: 100%; object-fit: contain; }
    .controls { display: flex; padding: 14px 20px; justify-content: space-between; border-top: 1px solid #1e1e2e; }
    button { padding: 8px 20px; border-radius: 8px; border: none; font-weight: 600; cursor: pointer; }
    #btn-connect { background: #2563eb; color: #fff; }
    #btn-disconnect { background: #1e1e2e; color: #ef4444; border: 1px solid #2e2e3e; }
  </style>
</head>
<body>
  <h2>Rescue Boat Operator Dashboard</h2>
  <div class="card">
    <div class="video-wrap">
      <img id="feed" alt="Video Feed">
    </div>
    <div class="controls">
      <span id="status">Disconnected</span>
      <div>
        <button id="btn-connect">Connect</button>
        <button id="btn-disconnect">Disconnect</button>
      </div>
    </div>
  </div>
  <script>
    const img = document.getElementById('feed');
    const btnConnect = document.getElementById('btn-connect');
    const btnDisc = document.getElementById('btn-disconnect');
    const status = document.getElementById('status');
    let ws = null;
    
    btnConnect.onclick = () => {
      ws = new WebSocket(`ws://${location.host}/ws`);
      ws.binaryType = 'blob';
      ws.onopen = () => status.textContent = 'Live';
      ws.onmessage = (e) => { img.src = URL.createObjectURL(e.data); };
      ws.onclose = () => status.textContent = 'Disconnected';
    };
    btnDisc.onclick = () => { if(ws) ws.close(); };
  </script>
</body>
</html>"""

def load_names(path: str) -> dict:
    if not os.path.exists(path): return {}
    with open(path) as f: return yaml.safe_load(f).get("names", {})

names = load_names(LABELS_PATH)
sess  = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"]) if os.path.exists(MODEL_PATH) else None
cap   = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

def process_frame(sess, frame):
    ih, iw = frame.shape[:2]
    sx, sy = iw / INPUT_W, ih / INPUT_H
    roi_y = int(ih * ROI_PERCENT / 100)

    blob = cv2.dnn.blobFromImage(frame, scalefactor=1/255.0, size=(INPUT_W, INPUT_H), swapRB=True, crop=False)
    dets = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]

    annotated = frame.copy()
    
    best_person = None
    highest_conf = 0.0

    # Draw ROI
    cv2.line(annotated, (0, roi_y), (iw, roi_y), (0, 255, 255), 2)
    cv2.putText(annotated, "DANGER ZONE BELOW", (10, roi_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    for x1m, y1m, x2m, y2m, conf, cls in dets:
        if conf < CONF_THRESH: continue
        if int(cls) != 0: continue # Only target class 0 (Person)

        if conf > highest_conf:
            highest_conf = conf
            best_person = (x1m, y1m, x2m, y2m, conf)

        x1, y1 = int(x1m * sx), int(y1m * sy)
        x2, y2 = int(x2m * sx), int(y2m * sy)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 0), 2)

    # ── Tracking Logic ────────────────────────────────────────────────────────
    if best_person:
        x1m, y1m, x2m, y2m, conf = best_person
        cx_pixel = int(((x1m + x2m) / 2) * sx)
        cy_pixel = int(((y1m + y2m) / 2) * sy)
        
        # Calculate steering (0-180 based on X position)
        rel_x = cx_pixel / iw
        steering_angle = int(rel_x * 180)
        
        # Calculate drop (if person crosses ROI)
        in_danger = cy_pixel > roi_y
        drop_cmd = 1 if in_danger else 0
        
        # Highlight target
        color = (0, 0, 255) if in_danger else (0, 255, 0)
        x1, y1 = int(x1m * sx), int(y1m * sy)
        x2, y2 = int(x2m * sx), int(y2m * sy)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 4)
        cv2.putText(annotated, f"TARGET LOCKED", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        
        # Send active commands
        send_to_arduino(steering=steering_angle, drop=drop_cmd, motor=1)
    else:
        # No person found: stop motor, center steering, don't drop
        send_to_arduino(steering=90, drop=0, motor=0)

    return annotated

@app.get("/")
async def index():
    return HTMLResponse(HTML)

@app.websocket("/ws")
async def detection_ws(ws: WebSocket):
    await ws.accept()
    if sess is None:
        await ws.close()
        return

    loop = asyncio.get_event_loop()
    try:
        while True:
            ok, frame = await loop.run_in_executor(None, cap.read)
            if not ok: break
            annotated = await loop.run_in_executor(None, process_frame, sess, frame)
            _, buf = cv2.imencode(".jpg", annotated)
            await ws.send_bytes(buf.tobytes())
            await asyncio.sleep(0.01)
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

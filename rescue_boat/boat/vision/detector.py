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
import socketio
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

logging.getLogger("websockets").setLevel(logging.CRITICAL)
ort.set_default_logger_severity(3)

# ── Configuration ─────────────────────────────────────────────────────────────
CAMERA_ID     = int(os.environ.get("CAMERA_ID", 0))
MODEL_PATH    = os.environ.get("MODEL_PATH", "/app/model.onnx")
LABELS_PATH   = os.environ.get("LABELS_PATH", "/app/coco8.yml")
CONF_THRESH   = float(os.environ.get("CONF_THRESH", "0.45"))
INPUT_W       = int(os.environ.get("INPUT_W", "640"))
INPUT_H       = int(os.environ.get("INPUT_H", "640"))
ROI_PERCENT   = float(os.environ.get("ROI_PERCENT", "60"))
SERIAL_PORT   = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD   = int(os.environ.get("SERIAL_BAUD", "9600"))
DASHBOARD_DIR = os.environ.get("DASHBOARD_DIR", "/app/dashboard")

# ── App & SocketIO ────────────────────────────────────────────────────────────
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()
sio_app = socketio.ASGIApp(sio, other_asgi_app=app)

# ── State ─────────────────────────────────────────────────────────────────────
current_mode = "scout"
target_coords = {"rel_x": None, "rel_y": None}

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


# ── ONNX Model & Camera ──────────────────────────────────────────────────────
def load_names(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f).get("names", {})


names = load_names(LABELS_PATH)
sess = (
    ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    if os.path.exists(MODEL_PATH)
    else None
)
cap = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


# ── Detection Logic ──────────────────────────────────────────────────────────
def process_frame(sess, frame):
    ih, iw = frame.shape[:2]
    sx, sy = iw / INPUT_W, ih / INPUT_H
    roi_y = int(ih * ROI_PERCENT / 100)

    blob = cv2.dnn.blobFromImage(
        frame, scalefactor=1 / 255.0, size=(INPUT_W, INPUT_H), swapRB=True, crop=False
    )
    dets = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]

    annotated = frame.copy()
    persons = []
    best_person = None
    highest_conf = 0.0

    # Draw ROI
    cv2.line(annotated, (0, roi_y), (iw, roi_y), (0, 255, 255), 2)
    cv2.putText(
        annotated, "DROP ZONE", (10, roi_y - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
    )

    for x1m, y1m, x2m, y2m, conf, cls in dets:
        if conf < CONF_THRESH:
            continue
        if int(cls) != 0:
            continue

        cx_pixel = int(((x1m + x2m) / 2) * sx)
        cy_pixel = int(((y1m + y2m) / 2) * sy)
        in_danger = cy_pixel > roi_y

        persons.append({
            "rel_x": round(cx_pixel / iw, 3),
            "rel_y": round(cy_pixel / ih, 3),
            "confidence": round(float(conf), 2),
            "in_danger": in_danger,
        })

        if conf > highest_conf:
            highest_conf = conf
            best_person = (x1m, y1m, x2m, y2m, conf, in_danger)

        x1, y1 = int(x1m * sx), int(y1m * sy)
        x2, y2 = int(x2m * sx), int(y2m * sy)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 0), 2)

    # ── Tracking & Arduino Commands ───────────────────────────────────────────
    if best_person:
        x1m, y1m, x2m, y2m, conf, in_danger = best_person
        cx_pixel = int(((x1m + x2m) / 2) * sx)
        rel_x = cx_pixel / iw
        steering_angle = int(rel_x * 180)
        drop_cmd = 1 if in_danger else 0

        color = (0, 0, 255) if in_danger else (0, 255, 0)
        x1, y1 = int(x1m * sx), int(y1m * sy)
        x2, y2 = int(x2m * sx), int(y2m * sy)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 4)
        cv2.putText(
            annotated, "TARGET LOCKED", (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2,
        )

        send_to_arduino(steering=steering_angle, drop=drop_cmd, motor=1)
    else:
        send_to_arduino(steering=90, drop=0, motor=0)

    return annotated, persons


# ── Dashboard (Static Files) ─────────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


# Mount static files for CSS, JS
app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


# Serve individual dashboard files (style.css, dashboard.js) at root level too
@app.get("/{filename:path}")
async def serve_dashboard_file(filename: str):
    # Don't serve for /api or /ws paths
    if filename.startswith("api/") or filename == "ws":
        return JSONResponse({"error": "not_found"}, status_code=404)
    filepath = os.path.join(DASHBOARD_DIR, filename)
    if os.path.isfile(filepath):
        return FileResponse(filepath)
    return JSONResponse({"error": "not_found"}, status_code=404)


# ── REST API ──────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def api_status():
    return {
        "ok": True,
        "mode": current_mode,
        "serial_dry_run": serial_dry_run,
        "target": target_coords,
    }


@app.post("/api/mode")
async def api_mode(request: Request):
    global current_mode
    data = await request.json()
    mode = data.get("mode")
    valid_modes = ("scout", "rescue", "supply_drop")
    if mode not in valid_modes:
        return JSONResponse({"ok": False, "error": f"Invalid mode: {mode}"}, status_code=400)
    current_mode = mode
    await sio.emit("status", {"mode": current_mode})
    return {"ok": True, "mode": current_mode}


@app.post("/api/target")
async def api_target(request: Request):
    global target_coords
    data = await request.json()
    target_coords = {
        "rel_x": data.get("rel_x"),
        "rel_y": data.get("rel_y"),
    }
    return {"ok": True, "target": target_coords}


@app.post("/api/drop")
async def api_drop():
    send_to_arduino(steering=90, drop=1, motor=0)
    return {"ok": True, "action": "supply_drop_triggered"}


@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "component": "boat"}


@app.get("/config")
async def config():
    return {"boat_url": "", "socketio_url": ""}


# ── WebSocket (Video Stream) ─────────────────────────────────────────────────
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
            if not ok:
                break
            annotated, persons = await loop.run_in_executor(
                None, process_frame, sess, frame
            )
            _, buf = cv2.imencode(".jpg", annotated)
            await ws.send_bytes(buf.tobytes())

            # Broadcast detection data via SocketIO
            if persons:
                await sio.emit("detection", {"persons": persons})

            await asyncio.sleep(0.01)
    except Exception:
        pass


# ── SocketIO Events ──────────────────────────────────────────────────────────
@sio.on("connect")
async def sio_connect(sid, environ):
    await sio.emit("status", {"mode": current_mode}, to=sid)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(sio_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

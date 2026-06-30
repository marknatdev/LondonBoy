"""
detector.py — PC-side detection server

Responsibilities:
  • Connect to boat's WebSocket at ws://BOAT_IP:5000/ws to receive raw camera frames
  • Run YOLO26n inference locally (ONNX Runtime)
  • Serve the Apple-inspired operator dashboard
  • Broadcast detection events via SocketIO
  • Send steering/drop/motor commands back to the boat via POST /api/serial
"""

import asyncio
import logging
import os
import json

import cv2
import numpy as np
import yaml
import onnxruntime as ort
import socketio
import httpx
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

logging.getLogger("websockets").setLevel(logging.CRITICAL)
ort.set_default_logger_severity(3)

# ── Configuration ─────────────────────────────────────────────────────────────
BOAT_IP       = os.environ.get("BOAT_IP", "192.168.1.100")
BOAT_PORT     = os.environ.get("BOAT_PORT", "5000")
BOAT_WS_URL   = f"ws://{BOAT_IP}:{BOAT_PORT}/ws"
BOAT_API_URL  = f"http://{BOAT_IP}:{BOAT_PORT}"

MODEL_PATH    = os.environ.get("MODEL_PATH", "/app/model.onnx")
LABELS_PATH   = os.environ.get("LABELS_PATH", "/app/coco8.yml")
CONF_THRESH   = float(os.environ.get("CONF_THRESH", "0.45"))
INPUT_W       = int(os.environ.get("INPUT_W", "640"))
INPUT_H       = int(os.environ.get("INPUT_H", "640"))
ROI_PERCENT   = float(os.environ.get("ROI_PERCENT", "60"))
DASHBOARD_DIR = os.environ.get("DASHBOARD_DIR", "/app/dashboard")

# ── App & SocketIO ────────────────────────────────────────────────────────────
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()
sio_app = socketio.ASGIApp(sio, other_asgi_app=app)

# ── State ─────────────────────────────────────────────────────────────────────
current_mode = "scout"
target_coords = {"rel_x": None, "rel_y": None}
latest_frame = None  # Latest annotated JPEG bytes for dashboard WebSocket clients
frame_lock = asyncio.Lock()
connected_viewers = set()

# ── HTTP client for sending commands to boat ──────────────────────────────────
http_client = httpx.AsyncClient(timeout=5.0)


async def send_to_boat(steering: int, drop: int, motor: int):
    try:
        await http_client.post(
            f"{BOAT_API_URL}/api/serial",
            json={"steering": steering, "drop": drop, "motor": motor},
        )
    except Exception as e:
        print(f"[boat-cmd] Failed: {e}")


# ── ONNX Model ───────────────────────────────────────────────────────────────
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


# ── Detection Logic ──────────────────────────────────────────────────────────
def process_frame(frame):
    if sess is None:
        return frame, []

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

    return annotated, persons, best_person


# ── Background: Pull frames from boat, run YOLO, push results ────────────────
async def boat_frame_loop():
    """Connects to the boat WebSocket, receives raw frames, runs detection."""
    global latest_frame

    while True:
        try:
            print(f"[boat] Connecting to {BOAT_WS_URL} ...")
            async with websockets.connect(BOAT_WS_URL, max_size=10_000_000) as ws:
                print(f"[boat] Connected!")
                while True:
                    data = await ws.recv()
                    # Decode raw JPEG from boat
                    np_arr = np.frombuffer(data, dtype=np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    # Run YOLO detection
                    loop = asyncio.get_event_loop()
                    annotated, persons, best_person = await loop.run_in_executor(
                        None, process_frame, frame
                    )

                    # Encode annotated frame for dashboard viewers
                    _, buf = cv2.imencode(".jpg", annotated)
                    frame_bytes = buf.tobytes()

                    async with frame_lock:
                        latest_frame = frame_bytes

                    # Send commands to boat based on detection
                    if best_person:
                        x1m, y1m, x2m, y2m, conf, in_danger = best_person
                        ih, iw = frame.shape[:2]
                        sx = iw / INPUT_W
                        cx_pixel = int(((x1m + x2m) / 2) * sx)
                        rel_x = cx_pixel / iw
                        steering_angle = int(rel_x * 180)
                        drop_cmd = 1 if in_danger else 0
                        await send_to_boat(steering=steering_angle, drop=drop_cmd, motor=1)
                    else:
                        await send_to_boat(steering=90, drop=0, motor=0)

                    # Broadcast detection data via SocketIO
                    if persons:
                        await sio.emit("detection", {"persons": persons})

        except Exception as e:
            print(f"[boat] Connection lost: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)


@app.on_event("startup")
async def startup():
    asyncio.create_task(boat_frame_loop())


# ── Dashboard (Static Files) ─────────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


@app.get("/{filename:path}")
async def serve_dashboard_file(filename: str):
    if filename.startswith("api/") or filename == "ws":
        return JSONResponse({"error": "not_found"}, status_code=404)
    filepath = os.path.join(DASHBOARD_DIR, filename)
    if os.path.isfile(filepath):
        return FileResponse(filepath)
    return JSONResponse({"error": "not_found"}, status_code=404)


# ── WebSocket: Stream annotated frames to dashboard viewers ──────────────────
@app.websocket("/ws")
async def dashboard_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            async with frame_lock:
                frame = latest_frame
            if frame:
                await ws.send_bytes(frame)
            await asyncio.sleep(0.03)  # ~30 FPS to browser
    except Exception:
        pass


# ── REST API ──────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def api_status():
    # Check boat connectivity
    try:
        resp = await http_client.get(f"{BOAT_API_URL}/api/ping")
        boat_data = resp.json()
        serial_dry_run = boat_data.get("serial_dry_run", True)
    except Exception:
        serial_dry_run = True
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
    target_coords = {"rel_x": data.get("rel_x"), "rel_y": data.get("rel_y")}
    return {"ok": True, "target": target_coords}


@app.post("/api/drop")
async def api_drop():
    await send_to_boat(steering=90, drop=1, motor=0)
    return {"ok": True, "action": "supply_drop_triggered"}


@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "component": "pc"}


@app.get("/config")
async def config():
    return {"boat_url": BOAT_API_URL, "socketio_url": ""}


# ── SocketIO Events ──────────────────────────────────────────────────────────
@sio.on("connect")
async def sio_connect(sid, environ):
    await sio.emit("status", {"mode": current_mode}, to=sid)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(sio_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

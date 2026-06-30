# Workshop 6: Object Detection with yolo26

## Objective

Run real-time object detection on a camera feed using a yolo26n ONNX model and OpenCV's `cv2.dnn` — stream annotated frames to a browser over WebSocket.

---

## What You Need

- Raspberry Pi (or any Linux machine with Python 3.10+)
- USB or CSI camera
- Docker installed on the Raspberry Pi
- Internet access to download `yolo26n.onnx` and `coco8.yml`

---

## Concepts

### System Architecture

```
Browser
       │  WebSocket  ws://<arduino-ip>:8080/ws
       ▼
detection_server.py  ── FastAPI + WebSocket server
       │  cap.read()
       ▼
USB Camera  ── raw BGR frame
       │  cv2.dnn.blobFromImage
       ▼
yolo26n ONNX model  ── onnxruntime.InferenceSession
       │  raw tensor [1, 300, 6]
       ▼
filter by conf + draw boxes  ── annotated JPEG frame
       │  ws.send_bytes
       ▼
Browser  ── displays live feed
```

### yolo26 Output Format

yolo26 is **end-to-end (NMS-free)**: NMS runs inside the model graph. It outputs a single tensor of shape `[1, 300, 6]` — at most 300 final detections, already deduplicated:

```
column 0  → x1   (box left,   in model input space)
column 1  → y1   (box top)
column 2  → x2   (box right)
column 3  → y2   (box bottom)
column 4  → conf (confidence, already 0.0–1.0)
column 5  → cls  (class id, 0–79 COCO)
rows      → up to 300 final detections, sorted by confidence
```

Each row is one finished detection. No anchor proposals, no separate NMS step, no objectness score. Just filter by `conf >= CONF_THRESH` and draw.

> **Note:** the older YOLOv8 export is different — `[84, 8400]`: 8400 raw anchor proposals (cx, cy, w, h + 80 class scores) that you must threshold *and* run NMS on yourself. yolo26 does both for you.

### Preprocessing Pipeline

```
frame (BGR, original size)
  └─ cv2.dnn.blobFromImage
       ├─ resize to 640×640
       ├─ scale pixel values × (1/255) → 0.0–1.0
       ├─ swap R↔B channels (BGR→RGB)
       └─ shape: [1, 3, 640, 640]
```

Rescale factors `sx = orig_w / 640` and `sy = orig_h / 640` convert model-space boxes back to pixel coordinates.

### Non-Maximum Suppression (NMS) — built in

Multiple overlapping boxes can fire for the same object. NMS keeps only the highest-confidence box when two boxes overlap too much.

With yolo26 you **don't write NMS** — it is baked into the exported graph. The `[1, 300, 6]` output is already deduplicated, so the server just filters by confidence. (The `IOU_THRESH` env var is unused with this model; it only matters for raw YOLOv8-style exports where you call `cv2.dnn.NMSBoxes` yourself.)

### WebSocket Frame Streaming

The server encodes each annotated frame as JPEG and sends raw bytes over WebSocket. The browser creates a Blob URL and sets it as the `<img>` src — no HTTP polling, no buffering delay.

---

## Part 1 — detection_server.py

### Create the file

Navigate to workshop root and create the directory:

```bash
cd $HOME/coding_th/workshop
mkdir -p workshop6/python/detection
cd workshop6/python/detection
vim detection_server.py
```

### The code

```python
import asyncio
import logging
import os
import cv2
import numpy as np
import yaml
import onnxruntime as ort
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

logging.getLogger("websockets").setLevel(logging.CRITICAL)
ort.set_default_logger_severity(3)  # ERROR — hide GPU device-probe warnings (Uno Q is CPU-only)

CAMERA_ID   = int(os.environ.get("CAMERA_ID", 0))
MODEL_PATH  = os.environ.get("MODEL_PATH", "model.onnx")
LABELS_PATH = os.environ.get("LABELS_PATH", "coco8.yml")
CONF_THRESH = float(os.environ.get("CONF_THRESH", "0.25"))
IOU_THRESH  = float(os.environ.get("IOU_THRESH", "0.45"))
INPUT_W     = int(os.environ.get("INPUT_W", "640"))
INPUT_H     = int(os.environ.get("INPUT_H", "640"))

app = FastAPI()

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Detection Feed</title>
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #0a0a0f;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-family: 'Segoe UI', system-ui, sans-serif;
      color: #e0e0e0;
      gap: 20px;
      padding: 24px;
    }
    header {
      display: flex;
      align-items: center;
      gap: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 13px;
      font-weight: 600;
      color: #666;
    }
    header svg { opacity: 0.6; }
    .card {
      background: #13131a;
      border: 1px solid #1e1e2e;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 8px 40px rgba(0,0,0,0.6);
      max-width: 900px;
      width: 100%;
    }
    .video-wrap {
      position: relative;
      background: #08080d;
      aspect-ratio: 16/9;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    #feed {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
      transition: opacity 0.3s;
    }
    #feed.hidden { opacity: 0; }
    .placeholder {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 12px;
      color: #333;
      font-size: 13px;
      pointer-events: none;
      transition: opacity 0.3s;
    }
    .placeholder svg { opacity: 0.3; }
    .placeholder.hidden { opacity: 0; }
    .pip {
      position: absolute;
      top: 12px;
      right: 12px;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #333;
      transition: background 0.3s, box-shadow 0.3s;
    }
    .pip.live {
      background: #22c55e;
      box-shadow: 0 0 8px #22c55e99;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 6px #22c55e88; }
      50%       { box-shadow: 0 0 14px #22c55ebb; }
    }
    .controls {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 20px;
      border-top: 1px solid #1e1e2e;
      gap: 12px;
      flex-wrap: wrap;
    }
    #status-text { font-size: 12px; color: #555; letter-spacing: 0.04em; }
    #status-text.connected  { color: #22c55e; }
    #status-text.connecting { color: #f59e0b; }
    #status-text.error      { color: #ef4444; }
    .btn-group { display: flex; gap: 8px; }
    button {
      padding: 8px 20px;
      border-radius: 8px;
      border: none;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.15s, transform 0.1s;
      letter-spacing: 0.03em;
    }
    button:active { transform: scale(0.97); }
    button:disabled { opacity: 0.35; cursor: not-allowed; }
    #btn-connect { background: #2563eb; color: #fff; }
    #btn-connect:not(:disabled):hover { background: #1d4ed8; }
    #btn-disconnect { background: #1e1e2e; color: #ef4444; border: 1px solid #2e2e3e; }
    #btn-disconnect:not(:disabled):hover { background: #2a1a1a; }
  </style>
</head>
<body>
  <header>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
    </svg>
    Detection Feed
  </header>
  <div class="card">
    <div class="video-wrap">
      <img id="feed" class="hidden" alt="">
      <div class="placeholder" id="placeholder">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
          <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
        </svg>
        No feed
      </div>
      <div class="pip" id="pip"></div>
    </div>
    <div class="controls">
      <span id="status-text">Disconnected</span>
      <div class="btn-group">
        <button id="btn-connect">Connect</button>
        <button id="btn-disconnect" disabled>Disconnect</button>
      </div>
    </div>
  </div>
  <script>
    const img         = document.getElementById('feed');
    const placeholder = document.getElementById('placeholder');
    const pip         = document.getElementById('pip');
    const statusText  = document.getElementById('status-text');
    const btnConnect  = document.getElementById('btn-connect');
    const btnDisc     = document.getElementById('btn-disconnect');
    const WS_URL      = `ws://${location.host}/ws`;
    let ws = null;
    let userDisconnected = false;
    function setStatus(state, text) {
      statusText.textContent = text;
      statusText.className = state;
      pip.className = 'pip' + (state === 'connected' ? ' live' : '');
    }
    function showFeed(show) {
      img.classList.toggle('hidden', !show);
      placeholder.classList.toggle('hidden', show);
    }
    function connect() {
      userDisconnected = false;
      btnConnect.disabled = true;
      btnDisc.disabled = false;
      setStatus('connecting', 'Connecting…');
      ws = new WebSocket(WS_URL);
      ws.binaryType = 'blob';
      ws.onopen = () => setStatus('connected', 'Live');
      ws.onmessage = (e) => {
        const prev = img.src;
        img.src = URL.createObjectURL(e.data);
        if (prev) URL.revokeObjectURL(prev);
        showFeed(true);
      };
      ws.onclose = () => {
        showFeed(false);
        btnConnect.disabled = false;
        btnDisc.disabled = true;
        if (userDisconnected) {
          setStatus('', 'Disconnected');
        } else {
          setStatus('error', 'Lost connection — retrying in 3s…');
          setTimeout(() => { if (!userDisconnected) connect(); }, 3000);
        }
      };
      ws.onerror = () => ws.close();
    }
    function disconnect() {
      userDisconnected = true;
      if (ws) ws.close();
    }
    btnConnect.addEventListener('click', connect);
    btnDisc.addEventListener('click', disconnect);
  </script>
</body>
</html>"""


def load_names(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("names", {})


def run_detection(sess, names: dict, frame: np.ndarray) -> np.ndarray:
    ih, iw = frame.shape[:2]
    sx, sy = iw / INPUT_W, ih / INPUT_H

    blob = cv2.dnn.blobFromImage(
        frame, scalefactor=1 / 255.0, size=(INPUT_W, INPUT_H),
        swapRB=True, crop=False
    )
    # yolo26 is end-to-end (NMS-free): output [1, N, 6] rows = [x1, y1, x2, y2, conf, cls]
    # coords are xyxy in model input space, conf already 0-1, NMS already applied.
    dets = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]  # [N, 6]

    annotated = frame.copy()

    for x1m, y1m, x2m, y2m, conf, cls in dets:
        if conf < CONF_THRESH:
            continue
        x1 = int(x1m * sx)
        y1 = int(y1m * sy)
        x2 = int(x2m * sx)
        y2 = int(y2m * sy)
        cls   = int(cls)
        conf  = float(conf)
        label = f"{names.get(cls, f'class {cls}')}  {conf:.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, label, (x1, max(y1 - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    return annotated


names = load_names(LABELS_PATH) if os.path.exists(LABELS_PATH) else {}
sess  = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"]) if os.path.exists(MODEL_PATH) else None
cap   = cv2.VideoCapture(CAMERA_ID)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


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
            if not ok:
                break
            annotated = await loop.run_in_executor(None, run_detection, sess, names, frame)
            _, buf = cv2.imencode(".jpg", annotated)
            await ws.send_bytes(buf.tobytes())
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
```

### What happens step by step

1. `ort.InferenceSession(MODEL_PATH)` — loads the yolo26n weights into ONNX Runtime (supports all modern opsets)
2. `cv2.VideoCapture(CAMERA_ID)` — opens the USB camera
3. `loop.run_in_executor(None, cap.read)` — reads camera frame on a thread pool so the async event loop is not blocked
4. `cv2.dnn.blobFromImage` — resizes frame to 640×640, normalizes to 0–1, swaps BGR→RGB, returns `[1, 3, 640, 640]`
5. `sess.run(None, {input_name: blob})[0][0]` — runs the model; returns final detections `[300, 6]` = `[x1, y1, x2, y2, conf, cls]`, already deduplicated by built-in NMS
6. `if conf < CONF_THRESH: continue` — drops detections below confidence threshold
7. `x1m..y2m` rescaled by `sx, sy` — converts model-space xyxy coordinates back to pixel coordinates
8. `cv2.imencode(".jpg", annotated)` → `ws.send_bytes` — sends annotated JPEG to browser each frame

---

## Part 2 — Labels File

Both files are provided. Download them:

```bash
mkdir -p models names
curl -L "https://gitlab.com/robotcitizens/workshop/coding-thailand/2026/coding_th_robotics/-/raw/main/docs/files/yolo26n.onnx?ref_type=heads&inline=false" -o models/yolo26n.onnx
curl -L "https://gitlab.com/robotcitizens/workshop/coding-thailand/2026/coding_th_robotics/-/raw/dev/uno-q/docs/files/coco8.yml" -o names/coco8.yml
```

Final layout:

```
workshop6/
└── python/detection/
    ├── detection_server.py
    ├── docker-compose.yml
    ├── models/
    │   └── yolo26n.onnx
    └── names/
        └── coco8.yml
```

---

## Run

### docker-compose.yml

Create in the same directory:

```bash
vim docker-compose.yml
```

```yaml
services:
  detection:
    image: nptttn/coding-th-robotics:2026
    command: python detection_server.py
    volumes:
      - ./detection_server.py:/app/detection_server.py
      - ./models/yolo26n.onnx:/app/model.onnx:ro
      - ./names/coco8.yml:/app/coco8.yml:ro
      - /dev:/dev
    environment:
      - CAMERA_ID=0
      - PORT=8080
      - MODEL_PATH=/app/model.onnx
      - LABELS_PATH=/app/coco8.yml
      - CONF_THRESH=0.5
      - IOU_THRESH=0.45
    ports:
      - "8080:8080"
    network_mode: host
    ipc: host
    privileged: true
    restart: unless-stopped
```

Key points:

| Setting | Why |
|---------|-----|
| `volumes: models/yolo26n.onnx:ro` | Mounts ONNX file read-only — no copy into image needed |
| `volumes: names/coco8.yml:ro` | Mounts labels file read-only |
| `volumes: /dev` | Exposes USB camera devices to the container |
| `network_mode: host` | Container shares host network — `http://<arduino-ip>:8080` works directly |
| `privileged: true` | Required for camera device access |

### Find the Pi's IP address

```bash
ip a
```

Look for the `inet` line under your network interface (e.g. `wlan0`):

```
4: wlan0: ...
    inet 192.168.1.42/xx ...
```

### Start the detection service

```bash
docker compose run --rm detection
```

Open browser at `http://<arduino-ip>:8080`, click **Connect** — live annotated feed appears.

### Tune with environment variables

```bash
CONF_THRESH=0.3 IOU_THRESH=0.5 docker compose run --rm detection
```

| Variable | Default | Effect |
|----------|---------|--------|
| `CAMERA_ID` | 0 | Which `/dev/video*` device to use |
| `CONF_THRESH` | 0.5 | Minimum confidence to show a box (lower = more detections, more false positives) |
| `IOU_THRESH` | 0.45 | Unused with yolo26 (NMS is built in); kept for raw YOLOv8-style models |
| `INPUT_W` / `INPUT_H` | 640 | Model input resolution — must match the exported model |
| `PORT` | 8080 | WebSocket server port |

---

## Exercises

### Change confidence threshold

Set `CONF_THRESH=0.1` — observe more false positives. Set `CONF_THRESH=0.8` — only high-certainty detections remain.

### Count detections per class

Modify `run_detection` to count how many boxes of each class are drawn and print it:

```python
from collections import Counter
counts = Counter(
    names.get(int(cls), "unknown")
    for *_, conf, cls in dets if conf >= CONF_THRESH
)
print(counts)
```

### Use a different model

Export `yolo26s.onnx` (small) or `yolo26m.onnx` (medium) for better accuracy at the cost of speed:

```bash
python3 -c "from ultralytics import YOLO; YOLO('yolo26s.pt').export(format='onnx')"
```

Mount the new model and set `MODEL_PATH=/app/model.onnx` in the compose file.

> Keep using a yolo26 (end-to-end) export so the `[N, 6]` output matches `run_detection`. A raw YOLOv8 export gives `[84, 8400]` and needs the old NMS code path.

---

## Next

Continue to [Workshop 7: State Machine — Stop on Red, Go on Green](WORKSHOP7.md).

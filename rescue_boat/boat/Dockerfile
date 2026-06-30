# ─────────────────────────────────────────────────────────────────────────────
# BOAT Dockerfile — runs on Arduino UNO Q (Debian Linux MPU)
#
# Responsibilities:
#   - USB Webcam capture
#   - YOLO26n person detection + ROI logic
#   - Lightweight REST API (no dashboard files)
#   - Serial bridge to STM32 MCU
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim-bookworm

LABEL component="boat"
LABEL description="Rescue Boat — Vision Pipeline + API Server (Arduino UNO Q)"

# ── System deps for OpenCV + serial ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libusb-1.0-0 \
    v4l-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ───────────────────────────────────────────────────────────────
COPY vision/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Pre-download YOLO model weights ───────────────────────────────────────────
RUN python -c "\
from ultralytics import YOLO; \
try: \
    YOLO('yolo26n.pt'); print('yolo26n.pt OK') \
except: \
    YOLO('yolo11n.pt'); print('yolo11n.pt OK (fallback)') \
"

# ── Copy boat source only ─────────────────────────────────────────────────────
COPY vision/  ./vision/
COPY server/  ./server/

# ── Environment ───────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV CAMERA_INDEX=0
ENV SERIAL_PORT=/dev/ttyACM0
ENV SERIAL_BAUD=9600
ENV ROI_LINE_PERCENT=60
ENV HOST=0.0.0.0
ENV PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

CMD ["python", "server/boat_app.py"]

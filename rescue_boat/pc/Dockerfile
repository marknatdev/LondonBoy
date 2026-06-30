# ─────────────────────────────────────────────────────────────────────────────
# PC Dockerfile — runs on the Operator's PC / laptop
#
# Responsibilities:
#   - Serve the web dashboard (HTML/CSS/JS)
#   - Proxy API calls to the boat (avoids browser CORS issues)
#   - No camera, no serial port, no YOLO needed
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim-bookworm

LABEL component="pc"
LABEL description="Rescue Boat — Operator Dashboard Server (PC)"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY server/  ./server/
COPY dashboard/ ./dashboard/

ENV PYTHONUNBUFFERED=1
# IP address of the boat on your WiFi network
ENV BOAT_IP=192.168.1.100
ENV BOAT_PORT=5000
ENV HOST=0.0.0.0
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

CMD ["python", "server/pc_app.py"]

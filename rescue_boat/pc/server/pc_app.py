"""
pc_app.py — Operator PC dashboard server.

Serves the dashboard HTML/CSS/JS and proxies all /api/* calls to the boat.
This means the browser never needs to know the boat's IP directly — everything
goes through this server.

The boat's address is set via environment variable:
  BOAT_IP=192.168.1.xxx
  BOAT_PORT=5000  (default)

Routes:
  GET  /               → Dashboard index.html
  GET  /<static>       → CSS / JS static files
  ANY  /api/*          → Proxied to http://BOAT_IP:BOAT_PORT/api/*
  GET  /api/video_feed → Streams proxied MJPEG from boat camera
"""

import os
import requests
from flask import Flask, Response, request, send_from_directory, jsonify

BOAT_IP   = os.getenv("BOAT_IP", "192.168.1.100")
BOAT_PORT = os.getenv("BOAT_PORT", "5000")
BOAT_BASE = f"http://{BOAT_IP}:{BOAT_PORT}"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")

app = Flask(__name__, static_folder=DASHBOARD_DIR)


# ── Dashboard static files ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    # Don't intercept /api routes
    if filename.startswith("api/"):
        return proxy(filename)
    return send_from_directory(DASHBOARD_DIR, filename)


# ── MJPEG video stream proxy ──────────────────────────────────────────────────
@app.route("/api/video_feed")
def video_proxy():
    """Stream the boat's MJPEG camera feed through to the browser."""
    boat_url = f"{BOAT_BASE}/api/video_feed"
    try:
        boat_resp = requests.get(boat_url, stream=True, timeout=5)
        return Response(
            boat_resp.iter_content(chunk_size=4096),
            content_type=boat_resp.headers.get(
                "Content-Type", "multipart/x-mixed-replace; boundary=frame"
            ),
        )
    except requests.exceptions.ConnectionError:
        return Response(
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n",
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )


# ── Generic API proxy ─────────────────────────────────────────────────────────
@app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path=""):
    boat_url = f"{BOAT_BASE}/api/{path}"
    try:
        resp = requests.request(
            method=request.method,
            url=boat_url,
            headers={k: v for k, v in request.headers if k != "Host"},
            data=request.get_data(),
            timeout=5,
            allow_redirects=False,
        )
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/json"),
        )
    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "boat_unreachable",
            "boat_url": boat_url,
            "hint": f"Is the boat running at {BOAT_BASE}?",
        }), 503


# ── Boat connection info (for dashboard) ──────────────────────────────────────
@app.route("/config")
def config():
    """Tell the dashboard the boat's SocketIO address for real-time events."""
    return jsonify({
        "boat_url":    BOAT_BASE,
        "socketio_url": BOAT_BASE,   # Dashboard connects SocketIO directly to boat
    })


if __name__ == "__main__":
    print(f"[pc] Dashboard  → http://localhost:{PORT}")
    print(f"[pc] Boat target→ {BOAT_BASE}")
    from gevent import pywsgi
    server = pywsgi.WSGIServer((HOST, PORT), app)
    server.serve_forever()

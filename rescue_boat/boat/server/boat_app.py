"""
boat_app.py — Lightweight API-only Flask server for the rescue boat.

This runs on the Arduino UNO Q Linux MPU. It does NOT serve the dashboard
HTML — that lives on the operator PC. The PC connects to this server over WiFi.

Endpoints:
  GET  /api/status      → JSON boat status (mode, detections, serial state)
  GET  /api/video_feed  → MJPEG camera stream (embedded in PC dashboard)
  POST /api/mode        → {"mode": "scout"|"rescue"|"supply_drop"}
  POST /api/target      → {"rel_x": 0.5, "rel_y": 0.8}
  POST /api/drop        → Trigger supply servo
  GET  /api/ping        → Health check

SocketIO events pushed to the PC dashboard:
  "detection"   → list of detected persons + danger flags
  "status"      → current mode + target
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, Response, jsonify, request
from flask_socketio import SocketIO

from vision.detector import Detector
from server.mode_manager import ModeManager
from server.serial_bridge import SerialBridge

# ── Config ────────────────────────────────────────────────────────────────────
HOST          = os.getenv("HOST", "0.0.0.0")
PORT          = int(os.getenv("PORT", "5000"))
CAMERA_INDEX  = int(os.getenv("CAMERA_INDEX", "0"))
CORS_ORIGINS  = os.getenv("CORS_ORIGINS", "*")   # Allow PC dashboard origin

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS, async_mode="gevent")

# ── Components ────────────────────────────────────────────────────────────────
serial_bridge = SerialBridge()
mode_manager  = ModeManager(serial_bridge)
detector      = Detector(camera_index=CAMERA_INDEX)


def _on_detection(detections: list[dict]):
    """Push detection events to all connected PC dashboards."""
    socketio.emit("detection", {"persons": detections})
    socketio.emit("status", mode_manager.status())


detector.on_detection = _on_detection

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "component": "boat"})


@app.route("/api/status")
def api_status():
    return jsonify({
        **mode_manager.status(),
        "serial_dry_run": serial_bridge.is_dry_run,
        "detections":     detector.latest_detections,
    })


@app.route("/api/video_feed")
def api_video_feed():
    """MJPEG stream — PC dashboard embeds this as <img src='http://boat-ip:5000/api/video_feed'>."""
    return Response(
        detector.mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/mode", methods=["POST"])
def api_mode():
    data = request.get_json(force=True)
    try:
        mode_manager.set_mode(data.get("mode", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "mode": data.get("mode")})


@app.route("/api/target", methods=["POST"])
def api_target():
    data = request.get_json(force=True)
    try:
        rel_x = float(data["rel_x"])
        rel_y = float(data["rel_y"])
    except (KeyError, ValueError):
        return jsonify({"error": "rel_x and rel_y required"}), 400
    mode_manager.set_target(rel_x, rel_y)
    return jsonify({"ok": True})


@app.route("/api/drop", methods=["POST"])
def api_drop():
    mode_manager.trigger_supply_drop()
    return jsonify({"ok": True})


# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    serial_bridge.connect()
    threading.Thread(target=detector.run, daemon=True).start()
    print(f"[boat] API server → http://{HOST}:{PORT}/api/")
    print(f"[boat] Video feed → http://{HOST}:{PORT}/api/video_feed")
    socketio.run(app, host=HOST, port=PORT, debug=False)

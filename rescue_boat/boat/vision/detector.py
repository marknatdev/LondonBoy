"""
detector.py — YOLO26n person detection with ROI danger-zone logic.

Responsibilities:
  - Capture frames from USB webcam (OpenCV)
  - Run YOLO26n inference (falls back to yolo11n if yolo26n unavailable)
  - Draw bounding boxes + ROI line on frame
  - Flag persons whose bbox center is below the ROI line as "in danger"
  - Provide a generator that yields MJPEG frames for the Flask video feed
  - Emit detection events (list of persons + danger status) via a callback
"""

import os
import time
import cv2
import numpy as np
from ultralytics import YOLO
from vision.roi_config import (
    ROI_LINE_PERCENT,
    ROI_LINE_COLOR, ROI_LINE_THICKNESS,
    SAFE_BOX_COLOR, DANGER_BOX_COLOR,
    LABEL_FONT_SCALE, LABEL_THICKNESS,
    CONFIDENCE_THRESHOLD, PERSON_CLASS_ID,
)

# ── Model loading ─────────────────────────────────────────────────────────────
def _load_model() -> YOLO:
    """Try YOLO26n first, fall back to yolo11n."""
    for model_name in ("yolo26n.pt", "yolo11n.pt"):
        try:
            model = YOLO(model_name)
            print(f"[detector] Loaded model: {model_name}")
            return model
        except Exception as exc:
            print(f"[detector] Could not load {model_name}: {exc}")
    raise RuntimeError("No YOLO model could be loaded.")


class Detector:
    """Wraps YOLO inference + ROI logic for the rescue boat camera."""

    def __init__(self, camera_index: int = 0):
        self.model = _load_model()
        self.camera_index = camera_index
        self.cap: cv2.VideoCapture | None = None
        self._running = False
        # Latest annotated frame (JPEG bytes) — shared with MJPEG stream
        self._latest_frame: bytes | None = None
        # Latest detection list — shared with Flask SocketIO
        self._latest_detections: list[dict] = []
        # Optional callback: called each frame with detections list
        self.on_detection = None

    # ── Camera lifecycle ──────────────────────────────────────────────────────
    def start(self):
        """Open the webcam."""
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera at index {self.camera_index}. "
                "Check that /dev/video0 is passed through to the container."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._running = True
        print(f"[detector] Camera {self.camera_index} opened (640x480).")

    def stop(self):
        """Release the webcam."""
        self._running = False
        if self.cap:
            self.cap.release()
            self.cap = None

    # ── Main inference loop ───────────────────────────────────────────────────
    def run(self):
        """Blocking loop — call in a background thread from app.py."""
        self.start()
        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                print("[detector] Frame read failed — retrying in 1s.")
                time.sleep(1)
                continue

            h, w = frame.shape[:2]
            roi_y = int(h * ROI_LINE_PERCENT / 100)

            # ── YOLO inference ────────────────────────────────────────────
            results = self.model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
            detections = []

            for result in results:
                for box in result.boxes:
                    cls_id = int(box.cls[0])
                    if cls_id != PERSON_CLASS_ID:
                        continue

                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    in_danger = cy > roi_y

                    detections.append({
                        "bbox": [x1, y1, x2, y2],
                        "center": [cx, cy],
                        "confidence": round(conf, 3),
                        "in_danger": in_danger,
                        # Relative position on frame for map (0.0–1.0)
                        "rel_x": round(cx / w, 3),
                        "rel_y": round(cy / h, 3),
                    })

                    # Draw bounding box
                    color = DANGER_BOX_COLOR if in_danger else SAFE_BOX_COLOR
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, LABEL_THICKNESS)

                    label = f"{'⚠ DANGER' if in_danger else 'SAFE'} {conf:.2f}"
                    label_y = max(y1 - 8, 16)
                    cv2.putText(
                        frame, label, (x1, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE,
                        color, LABEL_THICKNESS, cv2.LINE_AA,
                    )

            # ── Draw ROI line ─────────────────────────────────────────────
            cv2.line(frame, (0, roi_y), (w, roi_y),
                     ROI_LINE_COLOR, ROI_LINE_THICKNESS)
            cv2.putText(
                frame, "ROI — DANGER BELOW",
                (8, roi_y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                ROI_LINE_COLOR, 1, cv2.LINE_AA,
            )

            # ── Encode frame as JPEG for MJPEG stream ─────────────────────
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            self._latest_frame = jpeg.tobytes()
            self._latest_detections = detections

            # ── Fire callback ─────────────────────────────────────────────
            if self.on_detection:
                self.on_detection(detections)

    # ── MJPEG frame generator ─────────────────────────────────────────────────
    def mjpeg_generator(self):
        """Yield multipart JPEG bytes for Flask's streaming response."""
        while True:
            frame = self._latest_frame
            if frame is None:
                time.sleep(0.05)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame +
                b"\r\n"
            )
            time.sleep(1 / 25)  # ~25 fps cap

    @property
    def latest_detections(self) -> list[dict]:
        return self._latest_detections

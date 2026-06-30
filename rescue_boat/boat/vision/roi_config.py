"""
roi_config.py — ROI (Region of Interest) configuration for rescue boat
The ROI line divides the frame into SAFE (above) and DANGER (below) zones.
A person whose bounding box CENTER is below this line is flagged as in danger.
"""

import os

# ── ROI line position ─────────────────────────────────────────────────────────
# Percentage of frame height from the top (0–100).
# Default 60% = danger zone occupies the bottom 40% of the frame.
ROI_LINE_PERCENT: float = float(os.getenv("ROI_LINE_PERCENT", "60"))

# ── Visual style ──────────────────────────────────────────────────────────────
ROI_LINE_COLOR = (0, 220, 255)      # Cyan line (BGR)
ROI_LINE_THICKNESS = 2

SAFE_BOX_COLOR = (0, 200, 80)       # Green bbox — safe person (BGR)
DANGER_BOX_COLOR = (0, 60, 255)     # Red bbox  — person in danger (BGR)
LABEL_FONT_SCALE = 0.6
LABEL_THICKNESS = 2

# ── Detection thresholds ──────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD: float = 0.45  # Minimum YOLO confidence to show detection
PERSON_CLASS_ID: int = 0            # COCO class ID for "person"

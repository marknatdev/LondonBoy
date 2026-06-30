"""
mode_manager.py — Three-mode state machine for the rescue boat.

Modes:
  SCOUT        — Camera scans, detections are logged to the dashboard map.
                 No motor commands are sent.
  RESCUE       — Operator sets a target location. Boat drives toward target.
                 Sends drive/steer commands via serial bridge.
  SUPPLY_DROP  — Like RESCUE, but triggers the supply servo upon arrival.

The manager does not handle actual PID/path-planning (out of scope for
prototype). It translates operator intent → serial JSON commands.
"""

import threading
import time
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    SCOUT = "scout"
    RESCUE = "rescue"
    SUPPLY_DROP = "supply_drop"


class ModeManager:
    def __init__(self, serial_bridge):
        self.bridge = serial_bridge
        self._mode = Mode.SCOUT
        self._target: Optional[dict] = None   # {"rel_x": 0.5, "rel_y": 0.8}
        self._lock = threading.Lock()
        self._active_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────
    def set_mode(self, mode_str: str):
        """Switch operating mode. Stops any active movement."""
        with self._lock:
            try:
                new_mode = Mode(mode_str)
            except ValueError:
                raise ValueError(f"Unknown mode: '{mode_str}'. "
                                 f"Valid: {[m.value for m in Mode]}")
            self._mode = new_mode
            self._stop_active_thread()
            self.bridge.send({"cmd": "stop"})
            print(f"[mode] Switched to {new_mode.value.upper()}")

    def set_target(self, rel_x: float, rel_y: float):
        """Set navigation target (relative coords 0.0–1.0 on dashboard map)."""
        with self._lock:
            self._target = {"rel_x": rel_x, "rel_y": rel_y}
            print(f"[mode] Target set → rel_x={rel_x:.2f}, rel_y={rel_y:.2f}")
            if self._mode in (Mode.RESCUE, Mode.SUPPLY_DROP):
                self._start_navigation()

    def trigger_supply_drop(self):
        """Immediately command the supply servo to drop payload."""
        self.bridge.send({"cmd": "drop_supply"})
        print("[mode] Supply drop triggered.")

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def target(self) -> Optional[dict]:
        return self._target

    def status(self) -> dict:
        return {
            "mode": self._mode.value,
            "target": self._target,
        }

    # ── Internal navigation loop ──────────────────────────────────────────────
    def _stop_active_thread(self):
        if self._active_thread and self._active_thread.is_alive():
            self._stop_event.set()
            self._active_thread.join(timeout=2)
        self._stop_event.clear()

    def _start_navigation(self):
        """Spawn a background thread that steers toward the target."""
        self._stop_active_thread()
        self._active_thread = threading.Thread(
            target=self._navigation_loop, daemon=True
        )
        self._active_thread.start()

    def _navigation_loop(self):
        """
        Prototype navigation: proportional steering toward target.
        Uses rel_x to compute steering angle (0° = full left, 180° = full right).
        Drives forward at a fixed speed until stopped or mode changes.
        """
        target = self._target
        if target is None:
            return

        target_x = target["rel_x"]
        BASE_STEER = 90    # Servo neutral (degrees)

        print(f"[mode] Navigation started → target_x={target_x:.2f}")

        while not self._stop_event.is_set():
            # Simple P-controller: error = how far off-center the target is
            error = target_x - 0.5          # range: -0.5 … +0.5
            steer = int(BASE_STEER + error * 80)   # ±40° from neutral
            steer = max(50, min(130, steer))        # clamp to servo range

            # HL-51 relay: no speed field — motor runs at fixed RPM
            self.bridge.send({
                "cmd": "drive",
                "steering": steer,
            })
            time.sleep(0.2)

        # Arrived / mode changed — stop motors
        self.bridge.send({"cmd": "stop"})

        # In SUPPLY_DROP mode, trigger the drop servo after stopping
        if self._mode == Mode.SUPPLY_DROP:
            time.sleep(0.5)
            self.trigger_supply_drop()

        print("[mode] Navigation loop ended.")

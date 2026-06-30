"""
serial_bridge.py — UART bridge between Linux MPU and STM32 MCU.

Sends JSON command strings to the STM32 MCU over the serial port.
Reads telemetry lines back from the MCU (if any).
Falls back to a DryRun (no-op) mode if no serial port is available —
useful when running in Docker without physical hardware.
"""

import json
import os
import threading
import time
from typing import Callable

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "9600"))


class SerialBridge:
    def __init__(self):
        self._ser = None
        self._lock = threading.Lock()
        self._dry_run = False
        self._telemetry_callback: Callable[[dict], None] | None = None

    def connect(self):
        """Open serial port. Falls back to dry-run if unavailable."""
        try:
            import serial
            self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
            print(f"[serial] Connected to {SERIAL_PORT} @ {SERIAL_BAUD} baud.")
            # Start telemetry reader thread
            t = threading.Thread(target=self._read_loop, daemon=True)
            t.start()
        except Exception as exc:
            print(f"[serial] Cannot open {SERIAL_PORT}: {exc}")
            print("[serial] Running in DRY-RUN mode (no physical Arduino).")
            self._dry_run = True

    def send(self, command: dict):
        """Send a JSON command dict to the MCU."""
        payload = json.dumps(command) + "\n"
        if self._dry_run:
            print(f"[serial][DRY-RUN] >> {payload.strip()}")
            return
        with self._lock:
            try:
                self._ser.write(payload.encode("utf-8"))
            except Exception as exc:
                print(f"[serial] Write error: {exc}")

    def _read_loop(self):
        """Background thread: reads telemetry lines from MCU."""
        while self._ser and self._ser.is_open:
            try:
                line = self._ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    try:
                        data = json.loads(line)
                        if self._telemetry_callback:
                            self._telemetry_callback(data)
                    except json.JSONDecodeError:
                        pass  # Ignore malformed lines
            except Exception:
                time.sleep(0.1)

    def set_telemetry_callback(self, cb: Callable[[dict], None]):
        self._telemetry_callback = cb

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    @property
    def is_dry_run(self) -> bool:
        return self._dry_run

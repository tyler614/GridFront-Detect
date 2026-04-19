"""Background OAK-D discovery scanner.

Runs ``OakDriver.discover()`` on a timer (5 s by default) and caches the
result so the cameras-tab UI can poll a cheap endpoint instead of doing
a fresh broadcast every time.

The cache is per-device with a ``last_seen`` timestamp, which lets the UI
distinguish between "currently online", "recently online (likely
reconnecting)", and "long gone (offline)" without each client having to
keep its own decay timer.

This module is intentionally tiny — no live pipeline coupling, no config
mutation. The cameras endpoints in ``app.py`` read from here and decide
what to expose to the frontend.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# How often we broadcast for OAK-Ds. 5 s feels instant when plugging a
# camera in without flooding the LAN.
SCAN_INTERVAL_S = 5.0

# How long after the last sighting before a device is considered offline.
# Two missed scans plus a grace period.
OFFLINE_AFTER_S = 12.0


class _Scanner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # mx_id -> {mx_id, name, state, protocol, last_seen}
        self._cache: Dict[str, dict] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_scan_at: float = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="oak-camera-scanner", daemon=True
        )
        self._thread.start()
        logger.info("Camera scanner started (interval=%.1fs)", SCAN_INTERVAL_S)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        # Defer import so the scanner can be imported even when depthai
        # isn't available (e.g. in unit tests).
        try:
            from pipeline.oak_driver import OakDriver
        except Exception as e:  # pragma: no cover - environment-dependent
            logger.warning("Camera scanner disabled — depthai unavailable: %s", e)
            return

        while not self._stop.is_set():
            try:
                devices = OakDriver.discover()
                self._update(devices)
            except Exception:
                logger.exception("Camera discovery failed")
            self._stop.wait(SCAN_INTERVAL_S)

    def _update(self, devices: List[dict]) -> None:
        now = time.time()
        with self._lock:
            for d in devices:
                mx = d.get("mx_id")
                if not mx:
                    continue
                self._cache[mx] = {**d, "last_seen": now}
            self._last_scan_at = now

    # ── Read API ──────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a copy of the cache + scanner metadata."""
        now = time.time()
        with self._lock:
            devices = []
            for d in self._cache.values():
                devices.append({
                    **d,
                    "online": (now - d["last_seen"]) <= OFFLINE_AFTER_S,
                    "age_s": round(now - d["last_seen"], 1),
                })
            return {
                "devices": devices,
                "last_scan_at": self._last_scan_at,
                "scan_interval_s": SCAN_INTERVAL_S,
            }

    def is_online(self, device_id: Optional[str]) -> bool:
        """True if a device with this id (mx_id, name, or IP) is in the
        cache and was seen recently.
        """
        if not device_id:
            return False
        now = time.time()
        with self._lock:
            for d in self._cache.values():
                if device_id in (d.get("mx_id"), d.get("name")):
                    return (now - d["last_seen"]) <= OFFLINE_AFTER_S
        return False


# Module-level singleton — there's only one OAK network on a given host.
scanner = _Scanner()

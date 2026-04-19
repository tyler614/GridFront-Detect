"""
UDP broadcaster for ESP32 cab displays.

ESPs self-register via POST /api/register-display with their IP + UDP port.
A background thread polls the spatial detection state and fan-outs to every
registered display. Entries that stop heartbeating for REGISTRATION_TTL_S
are dropped automatically so we don't keep sending to disconnected ESPs.

Packet shape matches what esp32-display.ino expects:
    { "detections": [...], "summary": {...} }
Trimmed to the fields the firmware actually reads to keep it well under
the typical 1500-byte WiFi MTU.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict

from detection_state import get_state

logger = logging.getLogger(__name__)

REGISTRATION_TTL_S = 30.0     # drop ESPs silent for longer than this
BROADCAST_HZ = 15             # matches pipeline tick; lower CPU than 30
MAX_PACKET_BYTES = 1400       # stay under WiFi MTU (1500) minus UDP/IP header

# How old the pipeline state can be before we mark the link "stale" in the
# packet. The cab display flips to a CAMERA OFFLINE screen instead of
# rendering frozen detections — operators must know the system can no
# longer see, not stare at a 47-minute-old DANGER reading.
STATE_STALE_AFTER_S = 3.0

# Fields the firmware reads — anything else is stripped before send.
_DETECTION_KEYS = ("track_id", "x_m", "z_m", "distance_m", "zone")
_SUMMARY_KEYS = ("danger_count", "warning_count", "clear_count", "closest_m")

# Operator-facing display unit. The webview's settings page writes this via
# /api/units; every broadcast includes it so cab displays stay in sync with
# what the cab operator sees on the tablet.
_VALID_UNITS = ("m", "ft")


@dataclass
class _Display:
    ip: str
    port: int
    last_seen: float = field(default_factory=time.monotonic)


class DisplayBroadcaster:
    def __init__(self) -> None:
        self._displays: Dict[str, _Display] = {}
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._units = "m"

    # ── Units preference (shared across cab displays + webview) ──
    def set_units(self, units: str) -> str:
        u = (units or "").strip().lower()
        if u not in _VALID_UNITS:
            raise ValueError(f"units must be one of {_VALID_UNITS}")
        self._units = u
        return self._units

    def get_units(self) -> str:
        return self._units

    # ── Registration (called from Flask request handler) ─────
    def register(self, ip: str, port: int) -> None:
        key = f"{ip}:{port}"
        with self._lock:
            existing = self._displays.get(key)
            if existing:
                existing.last_seen = time.monotonic()
            else:
                self._displays[key] = _Display(ip=ip, port=port)
                logger.info("cab display registered: %s", key)

    def list_displays(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            return [
                {"ip": d.ip, "port": d.port, "age_s": round(now - d.last_seen, 1)}
                for d in self._displays.values()
            ]

    # ── Broadcast loop ───────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="display-bcast")
        self._thread.start()
        logger.info("DisplayBroadcaster started (%.0fHz)", BROADCAST_HZ)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self._sock.close()
        except OSError:
            pass

    def _run(self) -> None:
        interval = 1.0 / BROADCAST_HZ
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.warning("broadcast tick failed: %s", exc)
            time.sleep(interval)

    def _tick(self) -> None:
        # Prune stale registrations.
        now = time.monotonic()
        with self._lock:
            stale = [k for k, d in self._displays.items() if now - d.last_seen > REGISTRATION_TTL_S]
            for k in stale:
                logger.info("cab display TTL expired: %s", k)
                self._displays.pop(k, None)
            targets = list(self._displays.values())
        if not targets:
            return

        payload = self._build_payload()
        if payload is None:
            return
        data = payload.encode("utf-8")
        if len(data) > MAX_PACKET_BYTES:
            logger.warning("display packet too big (%d B) — truncating detections", len(data))
            data = self._build_payload(max_detections=6).encode("utf-8")

        for d in targets:
            try:
                self._sock.sendto(data, (d.ip, d.port))
            except OSError as exc:
                logger.debug("sendto %s:%d failed: %s", d.ip, d.port, exc)

    def _build_payload(self, max_detections: int | None = None) -> str | None:
        state = get_state()
        ts = state.get("timestamp")
        # Decide link freshness up-front. Stale = pipeline hasn't pushed a
        # frame in STATE_STALE_AFTER_S; the cab display flips to a CAMERA
        # OFFLINE screen rather than show frozen detections from minutes ago.
        link = "ok"
        if ts is None or (time.time() - float(ts)) > STATE_STALE_AFTER_S:
            link = "stale"

        # When stale, blank the detections/summary so the firmware never
        # has tempting data to render even if it ignores `link`.
        if link != "ok":
            return json.dumps({
                "detections": [],
                "summary": {k: 0 if k.endswith("_count") else None for k in _SUMMARY_KEYS},
                "units": self._units,
                "link": link,
                "ts": ts,
            })

        det_src = state.get("detections") or []
        if max_detections is not None:
            det_src = det_src[:max_detections]
        detections = [
            {k: v for k, v in d.items() if k in _DETECTION_KEYS}
            for d in det_src
        ]
        summary_src = state.get("summary") or {}
        summary = {k: summary_src.get(k) for k in _SUMMARY_KEYS}
        return json.dumps({
            "detections": detections,
            "summary": summary,
            "units": self._units,
            "link": link,
            "ts": ts,
        })


broadcaster = DisplayBroadcaster()

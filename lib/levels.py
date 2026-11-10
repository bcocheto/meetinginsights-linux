"""Live input levels for the recording screen, read from the WAV files that parec is writing.

No audio library needed: the files are 16 kHz mono signed 16-bit, so the last half second
is just the last 16000 bytes of the file.
"""
from __future__ import annotations

import math
import struct

RATE = 16000
HEADER = 44
FLOOR_DB = -90.0
QUIET_DB = -60.0      # below this nothing is really being picked up
DEAD_DB = -85.0       # essentially digital silence: muted, unplugged or the wrong device
DEAD_AFTER_S = 10
QUIET_AFTER_S = 30


def tail_db(path, seconds: float = 0.4) -> float | None:
    """RMS level in dBFS of the last `seconds` of a growing WAV file, or None if unreadable."""
    n = int(RATE * seconds) * 2
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            if size < HEADER + n:
                return None
            f.seek(size - n)
            data = f.read(n)
    except OSError:
        return None
    count = len(data) // 2
    if not count:
        return None
    samples = struct.unpack(f"<{count}h", data[:count * 2])
    rms = math.sqrt(sum(s * s for s in samples) / count) / 32768.0
    return max(FLOOR_DB, 20 * math.log10(rms)) if rms > 0 else FLOOR_DB


def as_fraction(db: float | None) -> float:
    """Map -60..0 dBFS onto 0..1 for a level bar."""
    if db is None:
        return 0.0
    return min(1.0, max(0.0, (db - QUIET_DB) / -QUIET_DB))


class Watch:
    """Remembers how long a channel has been silent, and says when to warn about it."""

    def __init__(self, start: float):
        self.since_sound = start     # last moment with a real signal
        self.since_alive = start     # last moment with anything above digital silence

    def update(self, db: float | None, now: float) -> None:
        if db is None:
            return
        if db > QUIET_DB:
            self.since_sound = now
        if db > DEAD_DB:
            self.since_alive = now

    def state(self, now: float) -> str:
        """'ok', 'quiet' (no sound for a while) or 'dead' (nothing at all)."""
        if now - self.since_alive >= DEAD_AFTER_S:
            return "dead"
        if now - self.since_sound >= QUIET_AFTER_S:
            return "quiet"
        return "ok"

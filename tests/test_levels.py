import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import levels  # noqa: E402


def write_wav(path, amplitude, seconds=1.0):
    n = int(levels.RATE * seconds)
    body = b"".join(struct.pack("<h", int(amplitude * math.sin(i / 7))) for i in range(n))
    Path(path).write_bytes(b"\0" * levels.HEADER + body)


class Levels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loud_quiet_and_silent(self):
        write_wav(self.dir / "loud.wav", 12000)
        write_wav(self.dir / "quiet.wav", 30)
        write_wav(self.dir / "zero.wav", 0)
        loud, quiet, zero = (levels.tail_db(self.dir / f"{n}.wav") for n in ("loud", "quiet", "zero"))
        self.assertGreater(loud, -15)
        self.assertLess(quiet, levels.QUIET_DB + 5)
        self.assertEqual(zero, levels.FLOOR_DB)

    def test_unreadable_or_too_short_is_none(self):
        self.assertIsNone(levels.tail_db(self.dir / "missing.wav"))
        (self.dir / "short.wav").write_bytes(b"\0" * 50)
        self.assertIsNone(levels.tail_db(self.dir / "short.wav"))

    def test_bar_fraction(self):
        self.assertEqual(levels.as_fraction(None), 0.0)
        self.assertEqual(levels.as_fraction(-90), 0.0)
        self.assertEqual(levels.as_fraction(0), 1.0)
        self.assertAlmostEqual(levels.as_fraction(-30), 0.5)

    def test_watch_warns_after_the_right_delay(self):
        w = levels.Watch(0)
        w.update(levels.FLOOR_DB, 5)
        self.assertEqual(w.state(5), "ok")
        self.assertEqual(w.state(levels.DEAD_AFTER_S), "dead")      # nothing at all
        w = levels.Watch(0)
        for t in range(5, 31, 5):
            w.update(-70, t)                                         # noise floor only
        self.assertEqual(w.state(20), "ok")
        self.assertEqual(w.state(30), "quiet")
        w.update(-20, 31)                                            # someone speaks
        self.assertEqual(w.state(31), "ok")


if __name__ == "__main__":
    unittest.main()

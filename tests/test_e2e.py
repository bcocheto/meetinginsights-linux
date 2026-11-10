"""Transcription quality gate. Skipped unless pointed at a recording and its reference text:

    MI_E2E_AUDIO=talk.wav MI_E2E_REFERENCE=talk.txt MI_E2E_MAX_WER=0.20 \
        python3 -m unittest tests.test_e2e

Run it with the app's Python (~/.local/share/minuta/venv/bin/python) so faster-whisper is available.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from wer import wer  # noqa: E402

AUDIO, REF = os.environ.get("MI_E2E_AUDIO"), os.environ.get("MI_E2E_REFERENCE")


@unittest.skipUnless(AUDIO and REF, "set MI_E2E_AUDIO and MI_E2E_REFERENCE to run")
class Quality(unittest.TestCase):
    def test_wer_stays_under_the_limit(self):
        limit = float(os.environ.get("MI_E2E_MAX_WER", "0.25"))
        model = os.environ.get("MI_E2E_MODEL", "small")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.txt"
            subprocess.run([sys.executable, str(ROOT / "lib" / "transcribe.py"), AUDIO, str(out), model, "Você", "Participante"],
                           check=True, capture_output=True, timeout=1800)
            got = wer(Path(REF).read_text(), out.read_text())
        self.assertLessEqual(got, limit, f"WER {got:.2%} is above the {limit:.0%} limit")


if __name__ == "__main__":
    unittest.main()

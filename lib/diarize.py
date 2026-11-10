#!/usr/bin/env python3
"""Tell apart the people on the far end of a call by the sound of their voice.

Your microphone and the call audio already arrive on separate channels, so "You" is
exact. When several people speak through the call they all share one channel; this
module splits that channel into "Participant 1", "Participant 2"... with an offline
speaker-diarization model (sherpa-onnx: pyannote segmentation + a speaker embedding
network). Everything runs on this computer.

  diarize.py --fetch                      download the two small models (~46 MB, once)
  diarize.py <audio.wav> <transcript.txt> <label-to-split> <prefix> [num_speakers]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("MINUTA_HOME", Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "minuta"))
DIR = DATA / "models" / "diarization"
SEG_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
           "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMB_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
           "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
SEG = DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB = DIR / "speaker-embedding.onnx"


def models_ready() -> bool:
    return SEG.is_file() and EMB.is_file()


def fetch() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    if not SEG.is_file():
        tmp = DIR / "seg.tar.bz2"
        urllib.request.urlretrieve(SEG_URL, tmp)
        with tarfile.open(tmp) as tf:
            tf.extractall(DIR, filter="data") if sys.version_info >= (3, 12) else tf.extractall(DIR)
        tmp.unlink(missing_ok=True)
    if not EMB.is_file():
        tmp = DIR / "emb.part"
        urllib.request.urlretrieve(EMB_URL, tmp)
        tmp.rename(EMB)
    print("diarization models ready", file=sys.stderr)
    return 0 if models_ready() else 1


def diarize(samples: np.ndarray, num_speakers: int = 0, threshold: float = 0.5):
    """samples: float32 mono @16 kHz -> [(start_s, end_s, speaker_index)]"""
    import sherpa_onnx as so
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEG)),
            num_threads=2),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(EMB), num_threads=2),
        clustering=so.FastClusteringConfig(num_clusters=num_speakers if num_speakers > 1 else -1,
                                           threshold=threshold),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = so.OfflineSpeakerDiarization(cfg)
    res = sd.process(samples.astype(np.float32)).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in res]


def split_words(samples: np.ndarray, words, num_speakers: int = 0):
    """words: [(start, end, text)] from Whisper -> [(start, voice_number, text)] or None.

    Splits at the moment the voice changes, even in the middle of one Whisper segment.
    Returns None when only one voice is found (nothing to split)."""
    if not words or not models_ready():
        return None
    segs = diarize(samples, num_speakers)
    if not segs:
        return None

    def voice_at(w0, w1):
        mid, best, dist = (w0 + w1) / 2, None, 1e9
        for s, e, spk in segs:
            if s <= mid <= e:
                return spk
            gap = min(abs(mid - s), abs(mid - e))
            if gap < dist:
                best, dist = spk, gap
        return best

    order, runs = {}, []
    for w0, w1, text in words:
        spk = voice_at(w0, w1)
        n = order.setdefault(spk, len(order) + 1)
        if runs and runs[-1][1] == n:
            runs[-1][2] += text
        else:
            runs.append([w0, n, text])
    if len(order) < 2:
        return None
    return [(st, n, tx.strip()) for st, n, tx in runs if tx.strip()]


def _load(wav: Path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "2", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)


def _secs(stamp: str) -> int:
    parts = [int(x) for x in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def relabel(wav: Path, txt: Path, target: str, prefix: str, num_speakers: int = 0) -> int:
    """Rewrite lines spoken by `target` as 'prefix 1', 'prefix 2'... by voice. In place."""
    if not models_ready():
        return 0
    lines = txt.read_text(encoding="utf-8").splitlines()
    rx = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)$")
    parsed = [rx.match(l.strip()) for l in lines]
    idx = [i for i, m in enumerate(parsed) if m and m.group(2).strip() == target]
    if len(idx) < 2:
        return 0
    stereo = _load(wav)
    # stereo recordings carry the far end on the right channel; mono files carry everyone
    far = stereo[:, 1] if abs(stereo[:, 0] - stereo[:, 1]).max() > 1e-4 else stereo[:, 0]
    if float(np.abs(far).max() or 0) < 0.003:
        return 0
    segs = diarize(far, num_speakers)
    if not segs:
        return 0

    starts = [_secs(m.group(1)) if m else None for m in parsed]
    order: dict[int, int] = {}
    labels: dict[int, int] = {}
    for i in idx:
        t0 = starts[i]
        nxt = next((starts[j] for j in range(i + 1, len(lines)) if starts[j] is not None and starts[j] > t0), None)
        t1 = min(nxt if nxt is not None else t0 + 6, t0 + 25)
        t1 = max(t1, t0 + 2)
        score: dict[int, float] = {}
        for s, e, spk in segs:
            ov = min(e, t1) - max(s, t0)
            if ov > 0:
                score[spk] = score.get(spk, 0) + ov
        if score:
            spk = max(score, key=score.get)
            order.setdefault(spk, len(order) + 1)
            labels[i] = order[spk]
    if len(order) < 2:
        return 0
    for i, n in labels.items():
        m = parsed[i]
        lines[i] = f"[{m.group(1)}] {prefix} {n}: {m.group(3)}"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(order)


def main(argv) -> int:
    if argv and argv[0] == "--fetch":
        return fetch()
    if len(argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    n = relabel(Path(argv[0]), Path(argv[1]), argv[2], argv[3], int(argv[4]) if len(argv) > 4 else 0)
    print(f"speakers found: {n}" if n else "no speaker split applied", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Load a faster-whisper model on the GPU when there is a usable one, else on the CPU.

The CUDA libraries come from the pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12
inside the app's own environment, so nothing is installed system-wide. The model is
read from the local cache; it is only downloaded when it is missing.
"""
from __future__ import annotations

import ctypes
import glob
import os
import site
import sys

_LIBS = ("nvidia/cublas/lib/libcublas.so.12", "nvidia/cublas/lib/libcublasLt.so.12",
         "nvidia/cudnn/lib/libcudnn.so.9", "nvidia/cuda_runtime/lib/libcudart.so.12")


def _preload_cuda() -> bool:
    found = 0
    for sp in site.getsitepackages():
        for pat in _LIBS:
            for f in glob.glob(os.path.join(sp, pat)):
                try:
                    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
                    found += 1
                except OSError:
                    return False
    return found >= 2


def cuda_available() -> bool:
    if os.environ.get("MEETINGINSIGHTS_DEVICE", "auto") == "cpu":
        return False
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            return False
    except Exception:  # noqa: BLE001
        return False
    return _preload_cuda()


def load_model(size: str, cpu_threads: int = 0):
    from faster_whisper import WhisperModel

    def make(device, local):
        kw = {"cpu_threads": cpu_threads} if device == "cpu" and cpu_threads else {}
        return WhisperModel(size, device=device, compute_type="int8", local_files_only=local, **kw)

    if cuda_available():
        try:
            model = make("cuda", True)
            print(f"model {size} on GPU", file=sys.stderr, flush=True)
            return model
        except Exception as e:  # noqa: BLE001 - out of memory, driver problem, not cached...
            print(f"GPU not used ({str(e)[:80]}); falling back to CPU", file=sys.stderr, flush=True)
    try:
        return make("cpu", True)
    except Exception:  # noqa: BLE001 - not cached: one-time download
        print(f"model {size} is not on disk yet; downloading it once", file=sys.stderr, flush=True)
        return make("cpu", False)


def options(live: bool = False) -> dict:
    """Decoding options from the user's settings (environment variables set by the CLI)."""
    env = os.environ.get
    opts = {}
    prompt = (env("MEETINGINSIGHTS_PROMPT") or "").strip()
    if prompt:
        opts["initial_prompt"] = prompt[:500]
    if not live:
        try:
            opts["beam_size"] = max(1, min(10, int(env("MEETINGINSIGHTS_BEAM", "5"))))
        except ValueError:
            opts["beam_size"] = 5
    return opts


def prepare(samples):
    """Optionally even out the volume so quiet voices are not missed."""
    if os.environ.get("MEETINGINSIGHTS_NORMALIZE", "off") != "on" or not len(samples):
        return samples
    import numpy as np
    peak = float(np.abs(samples).max())
    return samples if peak < 1e-4 else (samples * (0.9 / peak)).astype(np.float32)

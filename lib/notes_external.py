"""Write meeting notes with an external assistant CLI the user already has installed.

Providers: "claude-code" (the `claude` CLI) and "gemini-cli" (the `gemini` CLI).
This program never sees credentials: the CLI authenticates on its own with the
user's account. The transcript IS sent to that service, which is why this is
opt-in and off by default.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from glob import glob
from pathlib import Path

TIMEOUT_S = 240

SYSTEM = (
    "You turn a meeting transcript into structured notes. Use ONLY what is in the "
    "transcript; never invent people, facts, dates or commitments. Write in the same "
    "language as the transcript. Each line looks like '[mm:ss] Speaker: text'. "
    "Reply with a single JSON object and nothing else, with these keys: "
    '"summary": a list of 3 to 8 short factual sentences; '
    '"actions": a list of {"owner": <a speaker name exactly as written in the transcript, or "">, '
    '"action": <what must be done>, "t": <the [mm:ss] of the line it came from>}; '
    '"decisions": a list of {"speaker": <speaker name>, "text": <the decision>, "t": <mm:ss>}; '
    '"questions": a list of {"speaker": <speaker name>, "text": <the unresolved question>, "t": <mm:ss>}. '
    "Use empty lists when there is nothing for a key."
)


def available(provider: str) -> str | None:
    """Path of the provider's CLI, or None when it is not installed."""
    name = {"claude-code": "claude", "gemini-cli": "gemini"}.get(provider)
    if not name:
        return None
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local/bin" / name, home / ".claude/local" / name, Path("/usr/local/bin") / name]
    candidates += [Path(p) for p in sorted(glob(str(home / ".nvm/versions/node/*/bin" / name)), reverse=True)]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _command(provider: str, exe: str) -> list[str]:
    if provider == "claude-code":
        return [exe, "-p", "--no-session-persistence", "--tools", "",
                "--disable-slash-commands", "--system-prompt", SYSTEM, "--output-format", "text"]
    return [exe, "-p", SYSTEM + "\n\nThe transcript follows on standard input."]


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def write_notes(provider: str, turns: list[dict]):
    """Return (summaries, buckets) in the shape notes_local expects, or None on failure."""
    exe = available(provider)
    if not exe:
        return None
    transcript = "\n".join(f'[{t["t"]}] {t["speaker"]}: {t["text"]}' for t in turns)
    try:
        r = subprocess.run(_command(provider, exe), input=transcript, capture_output=True,
                           text=True, timeout=TIMEOUT_S, cwd=tempfile.gettempdir())
    except (subprocess.TimeoutExpired, OSError):
        return None
    data = _extract_json(r.stdout) if r.returncode == 0 else None
    if not isinstance(data, dict):
        return None

    speakers = {t["speaker"] for t in turns}
    times = {t["t"] for t in turns}

    def when(v):
        v = str(v or "").strip("[] ")
        return v if v in times else ""

    def who(v):
        return v if v in speakers else "—"

    summaries = [(turns[0]["t"], str(s).strip()) for s in data.get("summary", []) if str(s).strip()]
    buckets = {"action": [], "decision": [], "question": [], "discussion": []}
    for a in data.get("actions", []) or []:
        if isinstance(a, dict) and a.get("action"):
            buckets["action"].append({"speaker": who(a.get("owner")), "text": str(a["action"]).strip(),
                                      "t": when(a.get("t"))})
    for key, cls in (("decisions", "decision"), ("questions", "question")):
        for d in data.get(key, []) or []:
            if isinstance(d, dict) and d.get("text"):
                buckets[cls].append({"speaker": who(d.get("speaker")), "text": str(d["text"]).strip(),
                                     "t": when(d.get("t"))})
    return summaries, buckets

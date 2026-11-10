"""List and rename the speakers of a meeting, in the transcript and in the notes.

Transcript lines look like '[mm:ss] Speaker 2: text'. Renaming rewrites the speaker label on
those lines and every whole-word mention in the notes, so no model run is needed. Several old
names may map to one new name (that merges two voices).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

LINE = re.compile(r"^(\[\d{1,2}:\d{2}(?::\d{2})?\]\s+)([^:\n]+?)(:\s*.*)$")


def list_speakers(text: str) -> list[tuple[str, int]]:
    """Speakers in order of first appearance, with their number of lines."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = LINE.match(line.strip())
        if m:
            who = m.group(2).strip()
            counts[who] = counts.get(who, 0) + 1
    return list(counts.items())


def _clean(mapping: dict[str, str]) -> dict[str, str]:
    return {o.strip(): n.strip() for o, n in mapping.items() if o.strip() and n.strip() and o.strip() != n.strip()}


def rename_transcript(text: str, mapping: dict[str, str]) -> str:
    mapping = _clean(mapping)
    out = []
    for line in text.split("\n"):
        m = LINE.match(line)
        if m and m.group(2).strip() in mapping:
            line = m.group(1) + mapping[m.group(2).strip()] + m.group(3)
        out.append(line)
    return "\n".join(out)


def rename_notes(text: str, mapping: dict[str, str]) -> str:
    """Whole-word replacement, all names at once (so A->B and B->C never chain)."""
    mapping = _clean(mapping)
    if not mapping:
        return text
    names = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])")
    return pattern.sub(lambda m: mapping[m.group(1)], text)


def _write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def parse_pairs(args: list[str]) -> dict[str, str]:
    pairs = {}
    for a in args:
        old, sep, new = a.partition("=")
        if not sep or not old.strip() or not new.strip():
            raise ValueError(f"expected 'Old name=New name', got: {a!r}")
        pairs[old.strip()] = new.strip()
    return pairs


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "list":
        for who, n in list_speakers(Path(argv[2]).read_text(encoding="utf-8")):
            print(f"{who}\t{n}")
        return 0
    if len(argv) >= 5 and argv[1] == "rename":
        txt, notes = Path(argv[2]), Path(argv[3]) if argv[3] != "-" else None
        try:
            mapping = _clean(parse_pairs(argv[4:]))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        known = {w for w, _ in list_speakers(txt.read_text(encoding="utf-8"))}
        unknown = [o for o in mapping if o not in known]
        if unknown:
            print("no such speaker in the transcript: " + ", ".join(unknown), file=sys.stderr)
            return 1
        if not mapping:
            print("nothing to rename")
            return 0
        _write(txt, rename_transcript(txt.read_text(encoding="utf-8"), mapping))
        if notes and notes.is_file():
            _write(notes, rename_notes(notes.read_text(encoding="utf-8"), mapping))
        print(f"Renamed {len(mapping)} speaker(s)")
        return 0
    print("usage: speakers.py list <transcript> | rename <transcript> <notes|-> 'Old=New' ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

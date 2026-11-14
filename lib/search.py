"""Search across every meeting: notes and transcripts, by words and by client.

Matching ignores case and accents ("reuniao" finds "reunião") and needs every word of the
query to appear somewhere in the meeting. Results are ranked: title first, then the notes,
then the transcript. A quoted phrase must appear as written.
"""
from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})_(.*)$")
TURN_RE = re.compile(r"^\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)$")


def fold(text: str) -> str:
    """Lower-case and strip accents, so searches are forgiving."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def terms(query: str) -> list[str]:
    try:
        parts = shlex.split(query)
    except ValueError:                      # an unbalanced quote: treat it as plain words
        parts = query.replace('"', " ").split()
    return [t for t in (fold(p).strip() for p in parts) if t]


@dataclass
class Meeting:
    name: str                      # file stem, e.g. 2026-11-10_14-00_pricing-workshop
    title: str
    client: str = ""
    focus: str = ""
    notes: str = ""
    transcript: str = ""
    path: Path | None = None

    @property
    def date(self) -> str:
        m = STEM_RE.match(self.name)
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}" if m else ""


@dataclass
class Hit:
    meeting: Meeting
    score: int
    snippet: str = ""
    where: str = ""                # "title", "notes" or "transcript 12:34"
    found: list[str] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load(notes_dir: Path, rec_dir: Path) -> list[Meeting]:
    """Every meeting that has notes, newest first."""
    out = []
    for md in sorted(notes_dir.glob("*.md"), reverse=True) if notes_dir.exists() else []:
        notes = _read(md)
        first = notes.splitlines()[0] if notes else ""
        slug = STEM_RE.match(md.stem)
        title = first[2:].strip() if first.startswith("# ") and len(first) > 2 else \
            (slug.group(4) if slug else md.stem).replace("-", " ").title()
        meta = {}
        for line in _read(rec_dir / f"{md.stem}.meta").splitlines():
            k, _, v = line.partition("=")
            meta[k] = v
        out.append(Meeting(md.stem, title, meta.get("client", ""), meta.get("focus", ""), notes,
                           _read(rec_dir / f"{md.stem}.txt"), md))
    return out


def clients(meetings: list[Meeting]) -> list[str]:
    return sorted({m.client for m in meetings if m.client}, key=str.lower)


def _snippet(text: str, term: str, width: int = 70) -> str:
    folded = fold(text)
    i = folded.find(term)
    if i < 0:
        return ""
    a, b = max(0, i - width // 2), min(len(text), i + len(term) + width)
    s = text[a:b]
    s = re.sub(r"[*|#>_`]+", " ", s)                 # markdown furniture
    s = re.sub(r"(^|\s)-\s+", r"\1· ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def search(meetings: list[Meeting], query: str = "", client: str = "") -> list[Hit]:
    """Meetings matching the query (and the client, when given), best first; all of them if both are empty."""
    wanted = terms(query)
    hits = []
    for m in meetings:
        if client and fold(m.client) != fold(client):
            continue
        if not wanted:
            hits.append(Hit(m, 0))
            continue
        title, notes, trans = fold(m.title + " " + m.client), fold(m.notes), fold(m.transcript)
        score, ok = 0, True
        for t in wanted:
            in_title, in_notes, in_trans = t in title, t in notes, t in trans
            if not (in_title or in_notes or in_trans):
                ok = False
                break
            score += (6 if in_title else 0) + (3 if in_notes else 0) + (1 if in_trans else 0)
        if not ok:
            continue
        hit = Hit(m, score, found=wanted)
        # a readable place to show: the first term in the notes, else in the transcript
        for t in wanted:
            if t in notes and (s := _snippet(m.notes, t)):
                hit.snippet, hit.where = s, "notes"
                break
        else:
            for line in m.transcript.splitlines():
                turn = TURN_RE.match(line)
                if turn and any(t in fold(turn.group(3)) for t in wanted):
                    hit.snippet, hit.where = f"{turn.group(2)}: {turn.group(3)}", f"transcript {turn.group(1)}"
                    break
        if not hit.snippet and wanted[0] in title:
            hit.where = "title"
        hits.append(hit)
    hits.sort(key=lambda h: (-h.score, h.meeting.name), reverse=False)
    if not wanted:
        hits.sort(key=lambda h: h.meeting.name, reverse=True)
    return hits


if __name__ == "__main__":      # python3 lib/search.py <notes-dir> <rec-dir> [--client N] words...
    import sys
    args = sys.argv[1:]
    notes_dir, rec_dir = Path(args.pop(0)), Path(args.pop(0))
    client = ""
    if "--client" in args:
        i = args.index("--client")
        client = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    found = search(load(notes_dir, rec_dir), " ".join(f'"{a}"' if " " in a else a for a in args), client)
    for h in found:
        tag = f"  [{h.meeting.client}]" if h.meeting.client else ""
        print(f"{h.meeting.name}  {h.meeting.title}{tag}")
        if h.snippet:
            print(f"    {h.where}: {h.snippet}")
    if not found:
        print("No meetings found.", file=sys.stderr)
        sys.exit(1)

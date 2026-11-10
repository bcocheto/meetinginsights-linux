"""Export a meeting to an Obsidian vault as a note with frontmatter and links.

The vault is just a folder of Markdown files, so this only writes files, and only inside the
vault. Per client you can set a folder, a hub note to link back to and an index note that gets
a line for the new meeting, so the note is reachable from the rest of the vault.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})_(.*)$")
BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]]+')

WORDS = {
    "pt": {"type": "reuniao", "date": "data", "client": "cliente", "people": "participantes",
           "source": "fonte", "minutes": "min", "hub": "Hub", "transcript": "Transcrição",
           "source_text": "Minuta (transcrição automática; confira antes de agir)", "section": "Reuniões"},
    "en": {"type": "meeting", "date": "date", "client": "client", "people": "participants",
           "source": "source", "minutes": "min", "hub": "Hub", "transcript": "Transcript",
           "source_text": "Minuta (automatic transcript; check before acting)", "section": "Meetings"},
}


def _slug(text: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def client_config(clients_dir: Path, client: str) -> dict:
    """folder= / hub= / index= for a client, from ~/.config/minuta/clients/<slug>.cfg"""
    cfg = {}
    try:
        for line in (clients_dir / f"{_slug(client)}.cfg").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() and v.strip():
                cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


def _inside(vault: Path, rel: str) -> Path:
    """Resolve `rel` under the vault and refuse anything that escapes it."""
    target = (vault / rel.strip("/")).resolve()
    root = vault.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"{rel!r} is outside the vault")
    return target


def _link(rel_no_ext: str, label: str = "") -> str:
    rel_no_ext = rel_no_ext.strip("/")
    return f"[[{rel_no_ext}|{label}]]" if label else f"[[{rel_no_ext}]]"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _header_bits(notes: str):
    minutes = people = ""
    m = re.search(r"^\*(\d+)\s+\S+\s+·\s+\d+\s+\S+\s+·\s+[^:]+:\s*(.+?)\*\s*$", notes, re.M)
    if m:
        minutes, people = m.group(1), [p.strip() for p in m.group(2).split(",") if p.strip()]
    return minutes, people or []


def build_note(name: str, notes: str, transcript: str, client: str, focus: str, hub: str,
               lang: str, include_transcript: bool = True, now: dt.date | None = None) -> tuple[str, str]:
    """Return (file name without .md, note text)."""
    w = WORDS.get(lang, WORDS["en"])
    m = STEM_RE.match(name)
    date = m.group(1) if m else (now or dt.date.today()).isoformat()
    first = notes.splitlines()[0] if notes else ""
    title = first[2:].strip() if first.startswith("# ") else (m.group(4) if m else name).replace("-", " ").title()
    minutes, people = _header_bits(notes)
    today = (now or dt.date.today()).isoformat()

    tags = ["reuniao" if lang == "pt" else "meeting", "minuta"] + ([_slug(client)] if client else [])
    fm = ["---", f"type: {w['type']}", f"created: {date}", f"updated: {today}", f"{w['date']}: {date}"]
    if client:
        fm.append(f'{w["client"]}: "{client}"')
    if people:
        fm.append(f"{w['people']}: [{', '.join(people)}]")
    if minutes:
        fm.append(f"duration_{w['minutes']}: {minutes}")
    fm += [f"tags: [{', '.join(tags)}]", f"{w['source']}: {w['source_text']}", f"meeting: {name}", "---", ""]

    body = notes.rstrip("\n").splitlines()
    if body and body[0].startswith("# "):
        body[0] = f"# {title}"
    out = body[:1] + [""]
    if hub:
        out += [f"{w['hub']}: {hub}", ""]
    rest = body[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    out += rest
    text = "\n".join(fm + out).rstrip() + "\n"
    if include_transcript and transcript.strip():
        quoted = "\n".join(f"> {ln}" if ln.strip() else ">" for ln in transcript.strip().splitlines())
        text += f"\n> [!note]- {w['transcript']}\n{quoted}\n"
    clean = re.sub(r"\s+", " ", BAD_CHARS.sub(" ", title)).strip()
    return f"{date} - {clean}", text


def _note_path(folder: Path, base: str, name: str) -> Path:
    """Same meeting -> same file (so re-exporting updates it); a different note that already
    uses the name is never overwritten."""
    p = folder / f"{base}.md"
    n = 2
    while p.exists() and f"meeting: {name}" not in _read(p):
        p = folder / f"{base} ({n}).md"
        n += 1
    return p


def _add_to_index(index: Path, link: str, date: str, title: str, summary: str) -> bool:
    """Add the meeting to an index note: a row if it has a table, else a bullet. False if already there."""
    text = _read(index)
    target = re.escape(link[2:].split("|")[0].rstrip("]"))
    if not text or re.search(target + r"(\\?\||\]\])", text):     # already listed, as [[x]] or [[x|label]]
        return False
    lines = text.rstrip("\n").split("\n")
    rows = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("|")]
    esc = link.replace("|", "\\|")
    if rows:
        last = rows[-1]
        cols = len(re.findall(r"(?<!\\)\|", lines[last])) - 1      # unescaped pipes only
        cells = [date, esc] + ([summary] if cols >= 3 else []) + [""] * max(0, cols - 3)
        lines.insert(last + 1, "| " + " | ".join(cells[:cols]) + " |")
    else:
        lines.append(f"- {date} {link}")
    out = "\n".join(lines) + "\n"
    out = re.sub(r"^(updated:\s*)\S+", lambda m: m.group(1) + dt.date.today().isoformat(), out, count=1, flags=re.M)
    index.write_text(out, encoding="utf-8")
    return True


def export(name: str, notes_dir: Path, rec_dir: Path, vault: Path, folder_tpl: str, clients_dir: Path,
           lang: str = "en", include_transcript: bool = True, folder: str = "") -> dict:
    notes = _read(notes_dir / f"{name}.md")
    if not notes:
        raise FileNotFoundError(f"no notes for {name}")
    if not vault.is_dir():
        raise FileNotFoundError(f"the vault folder does not exist: {vault}")
    meta = {}
    for line in _read(rec_dir / f"{name}.meta").splitlines():
        k, _, v = line.partition("=")
        meta[k] = v
    client, focus = meta.get("client", ""), meta.get("focus", "")
    cfg = client_config(clients_dir, client) if client else {}

    rel_folder = folder or cfg.get("folder") or folder_tpl.replace("{client}", BAD_CHARS.sub(" ", client).strip() or "Inbox")
    target_dir = _inside(vault, rel_folder)
    hub_link = _link(cfg["hub"].removesuffix(".md"), client) if cfg.get("hub") else ""
    base, text = build_note(name, notes, _read(rec_dir / f"{name}.txt"), client, focus, hub_link, lang, include_transcript)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _note_path(target_dir, base, name)
    path.write_text(text, encoding="utf-8")

    result = {"path": str(path), "indexed": False}
    if cfg.get("index"):
        idx = _inside(vault, cfg["index"] if cfg["index"].endswith(".md") else cfg["index"] + ".md")
        rel = path.relative_to(vault.resolve()).with_suffix("").as_posix()
        title = base.split(" - ", 1)[-1]
        summ = re.search(r"^- \*\*(.+?)\*\*", notes, re.M)
        result["indexed"] = _add_to_index(idx, _link(rel, title), base[:10], title,
                                          (summ.group(1) if summ else "")[:110])
    return result


if __name__ == "__main__":
    import sys
    # python3 obsidian.py <name> <notes-dir> <rec-dir> <vault> <folder-template> <clients-dir> <lang> <with-transcript 1|0> [folder]
    a = sys.argv[1:]
    try:
        r = export(a[0], Path(a[1]), Path(a[2]), Path(a[3]).expanduser(), a[4], Path(a[5]), a[6], a[7] == "1",
                   a[8] if len(a) > 8 else "")
    except (OSError, ValueError) as e:
        print(f"obsidian: {e}", file=sys.stderr)
        sys.exit(1)
    print(r["path"])
    if r["indexed"]:
        print("added to the index")

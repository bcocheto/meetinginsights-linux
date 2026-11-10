"""Send the action items of a meeting to a Trello list, as cards. Opt-in, and only on request.

This is the one place the app talks to a service on purpose: it sends the text of the action
items you choose (and the meeting title) to Trello. Credentials are a Trello API key and token
that you create yourself; they live in a file only your user can read and are sent in the
request body over HTTPS, never in a URL.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.trello.com/1"
HEADINGS = ("action items", "itens de ação")
ID_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")
STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})_(.*)$")


class TrelloError(Exception):
    pass


# ---------- reading the notes ----------
def parse_actions(notes: str) -> list[dict]:
    """The rows of the Action Items table: [{owner, text, t}]."""
    out, inside = [], False
    for line in notes.splitlines():
        s = line.strip()
        if s.startswith("## "):
            inside = s[3:].strip().lower() in HEADINGS
            continue
        if not inside or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue                                   # the separator row
        if cells[1].lower() in ("action", "ação", "acao") and len(out) == 0 and cells[0].lower() in (
                "owner", "responsável", "responsavel"):
            continue                                   # the header row
        out.append({"owner": cells[0], "text": cells[1], "t": cells[2] if len(cells) > 2 else ""})
    return out


def title_of(notes: str, name: str) -> str:
    first = notes.splitlines()[0] if notes else ""
    if first.startswith("# ") and len(first) > 2:
        return first[2:].strip()
    m = STEM_RE.match(name)
    return (m.group(4) if m else name).replace("-", " ").title()


def action_id(meeting: str, a: dict) -> str:
    return hashlib.sha1(f"{meeting}\0{a['owner']}\0{a['text']}".encode()).hexdigest()[:16]


def card_for(a: dict, meeting: str, title: str) -> dict:
    m = STEM_RE.match(meeting)
    when = f"{m.group(1)} {m.group(2)}:{m.group(3)}" if m else ""
    desc = [f"Owner: {a['owner']}"] if a["owner"] and a["owner"] != "—" else []
    desc.append(f"Meeting: {title}" + (f" ({when})" if when else ""))
    if a["t"]:
        desc.append(f"At: {a['t']} in the recording")
    desc.append("\nCreated by Minuta.")
    return {"name": a["text"][:512], "desc": "\n".join(desc)}


# ---------- credentials ----------
def creds_path(config_dir: Path) -> Path:
    return config_dir / "trello"


def load_creds(config_dir: Path) -> tuple[str, str]:
    key, token = os.environ.get("MINUTA_TRELLO_KEY", ""), os.environ.get("MINUTA_TRELLO_TOKEN", "")
    if not (key and token):
        try:
            for line in creds_path(config_dir).read_text().splitlines():
                k, _, v = line.partition("=")
                if k == "key":
                    key = key or v.strip()
                elif k == "token":
                    token = token or v.strip()
        except OSError:
            pass
    return key, token


def save_creds(config_dir: Path, key: str, token: str) -> None:
    key, token = key.strip(), token.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", key) or not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", token):
        raise TrelloError("the key and the token should be the long letters-and-digits strings Trello gives you")
    config_dir.mkdir(parents=True, exist_ok=True)
    p = creds_path(config_dir)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # private from the first byte
    with os.fdopen(fd, "w") as f:
        f.write(f"key={key}\ntoken={token}\n")
    os.chmod(p, 0o600)


# ---------- the API ----------
def call(method: str, path: str, config_dir: Path, params: dict | None = None):
    key, token = load_creds(config_dir)
    if not (key and token):
        raise TrelloError("not connected to Trello: run  minuta trello login")
    base = os.environ.get("MINUTA_TRELLO_URL", API).rstrip("/")
    body = urllib.parse.urlencode({**(params or {}), "key": key, "token": token}).encode()
    req = urllib.request.Request(base + path, data=body, method=method,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        e.close()
        hint = {401: "the key or token was refused; run  minuta trello login",
                404: "not found: is the list still there?", 429: "Trello says slow down; try again in a minute"}
        raise TrelloError(hint.get(e.code, f"Trello answered {e.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TrelloError(f"could not reach Trello: {getattr(e, 'reason', e)}") from None


def boards(config_dir: Path):
    return [(b["id"], b["name"]) for b in call("GET", "/members/me/boards", config_dir, {"fields": "name", "filter": "open"})]


def lists(config_dir: Path, board: str):
    if not ID_RE.match(board):
        raise TrelloError("invalid board id")
    return [(x["id"], x["name"]) for x in call("GET", f"/boards/{board}/lists", config_dir, {"fields": "name", "filter": "open"})]


# ---------- what was already sent ----------
def sent_path(rec_dir: Path, name: str) -> Path:
    return rec_dir / f"{name}.trello"


def load_sent(rec_dir: Path, name: str) -> dict:
    try:
        return json.loads(sent_path(rec_dir, name).read_text())
    except (OSError, ValueError):
        return {}


def actions_for(name: str, notes_dir: Path, rec_dir: Path) -> list[dict]:
    try:
        notes = (notes_dir / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        raise TrelloError(f"no notes for {name}") from None
    sent = load_sent(rec_dir, name)
    acts = parse_actions(notes)
    for i, a in enumerate(acts, 1):
        a["i"], a["id"] = i, action_id(name, a)
        a["sent"] = sent.get(a["id"], "")
    return acts


def send(name: str, notes_dir: Path, rec_dir: Path, config_dir: Path, list_id: str,
         only: set[int] | None = None, dry_run: bool = False) -> list[dict]:
    if not ID_RE.match(list_id or ""):
        raise TrelloError("no list chosen: minuta trello use <list-id>")
    notes = (notes_dir / f"{name}.md").read_text(encoding="utf-8")
    title = title_of(notes, name)
    sent = load_sent(rec_dir, name)
    results = []
    for a in actions_for(name, notes_dir, rec_dir):
        if only is not None and a["i"] not in only:
            continue
        if a["sent"]:
            results.append({**a, "status": "already sent"})
            continue
        card = card_for(a, name, title)
        if dry_run:
            results.append({**a, "status": "would create", "card": card})
            continue
        made = call("POST", "/cards", config_dir, {"idList": list_id, **card})
        sent[a["id"]] = made.get("shortUrl") or made.get("url") or made.get("id", "sent")
        sent_path(rec_dir, name).write_text(json.dumps(sent, indent=1))    # saved per card: a failure keeps the rest
        results.append({**a, "status": "created", "url": sent[a["id"]]})
    return results


def main(argv: list[str]) -> int:
    # trello.py <cmd> <notes-dir> <rec-dir> <config-dir> [args...]
    cmd, notes_dir, rec_dir, config_dir, *args = argv
    notes_dir, rec_dir, config_dir = Path(notes_dir), Path(rec_dir), Path(config_dir)
    try:
        if cmd == "login":
            key, token = (sys.stdin.readline(), sys.stdin.readline())
            save_creds(config_dir, key, token)
            me = call("GET", "/members/me", config_dir, {"fields": "fullName,username"})
            print(f"connected as {me.get('fullName') or me.get('username')}")
        elif cmd == "logout":
            creds_path(config_dir).unlink(missing_ok=True)
            print("disconnected")
        elif cmd == "status":
            me = call("GET", "/members/me", config_dir, {"fields": "fullName,username"})
            print(f"connected as {me.get('fullName') or me.get('username')}")
        elif cmd == "boards":
            for i, n in boards(config_dir):
                print(f"{i}\t{n}")
        elif cmd == "lists":
            for i, n in lists(config_dir, args[0]):
                print(f"{i}\t{n}")
        elif cmd == "actions":
            print(json.dumps(actions_for(args[0], notes_dir, rec_dir), ensure_ascii=False))
        elif cmd == "send":
            name, list_id = args[0], args[1]
            only = {int(x) for x in args[2].split(",") if x.strip().isdigit()} if len(args) > 2 and args[2] else None
            res = send(name, notes_dir, rec_dir, config_dir, list_id, only, dry_run=(len(args) > 3 and args[3] == "1"))
            for r in res:
                print(f"{r['status']}: {r['text'][:90]}" + (f"  {r['url']}" if r.get("url") else ""))
            if not res:
                print("no action items to send")
        else:
            raise TrelloError(f"unknown command: {cmd}")
    except (TrelloError, IndexError, ValueError) as e:
        print(f"trello: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

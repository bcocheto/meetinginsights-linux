"""A GNOME custom keyboard shortcut that runs `minuta toggle` (start / stop the recording).

Works through gsettings, so it needs no extra service and works on Wayland. Other custom
shortcuts are never touched; only the entry named 'minuta' is added or removed.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys

BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
PATH = BASE + "minuta/"
SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
ACCEL = re.compile(r"^(<(Super|Control|Primary|Alt|Shift)>)+[A-Za-z0-9_]+$|^F([1-9]|1[0-2])$")


def gs(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "gsettings failed")
    return r.stdout.strip()


def _list() -> list[str]:
    raw = gs("get", SCHEMA, "custom-keybindings")
    raw = re.sub(r"^@as\s*", "", raw)
    return list(ast.literal_eval(raw))


def _binding_of(path: str) -> str:
    return ast.literal_eval(gs("get", f"{SCHEMA}.custom-keybinding:{path}", "binding"))


def show() -> str:
    return _binding_of(PATH) if PATH in _list() else ""


def conflicts(accel: str) -> list[str]:
    out = []
    for p in _list():
        if p != PATH:
            try:
                if _binding_of(p) == accel:
                    out.append(ast.literal_eval(gs("get", f"{SCHEMA}.custom-keybinding:{p}", "name")))
            except (RuntimeError, ValueError, SyntaxError):
                pass
    return out


def set_shortcut(accel: str, command: str) -> None:
    if not ACCEL.match(accel):
        raise ValueError(f"not a valid shortcut: {accel!r} (example: <Super><Alt>r)")
    clash = conflicts(accel)
    if clash:
        raise ValueError(f"{accel} is already used by: {', '.join(clash)}")
    item = f"{SCHEMA}.custom-keybinding:{PATH}"
    gs("set", item, "name", "Minuta: start or stop the recording")
    gs("set", item, "command", command)
    gs("set", item, "binding", accel)
    paths = _list()
    if PATH not in paths:
        gs("set", SCHEMA, "custom-keybindings", str(paths + [PATH]))


def remove() -> bool:
    paths = _list()
    if PATH not in paths:
        return False
    gs("set", SCHEMA, "custom-keybindings", str([p for p in paths if p != PATH]) if len(paths) > 1 else "[]")
    item = f"{SCHEMA}.custom-keybinding:{PATH}"
    for key in ("name", "command", "binding"):
        gs("reset", item, key)
    return True


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "show"
    try:
        if op == "show":
            b = show()
            print(b or "not set")
            return 0 if b else 1
        if op == "set" and len(argv) >= 4:
            set_shortcut(argv[2], argv[3])
            print(f"Shortcut {argv[2]} now runs: {argv[3]}")
            return 0
        if op == "remove":
            print("Shortcut removed" if remove() else "no shortcut was set")
            return 0
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print("usage: shortcut.py show | set <accelerator> <command> | remove", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

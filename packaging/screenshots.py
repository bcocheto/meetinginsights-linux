#!/usr/bin/env python3
"""Take the README screenshots from made-up demo data, in a throwaway home directory.

    GDK_BACKEND=x11 python3 packaging/screenshots.py [output-dir]      (default: docs/screenshots)

Needs ImageMagick (`import`).

Nothing from your real meetings is used. Needs a graphical session; models/venv are linked
from ~/.local/share/meetinginsights only so that the app considers itself ready.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"

TMP = Path(tempfile.mkdtemp(prefix="mi-shots-"))
HOME, NOTES, REC, CFG = TMP / "home", TMP / "notes", TMP / "home" / "rec", TMP / "cfg"
for d in (REC, NOTES, CFG / "meetinginsights" / "clients"):
    d.mkdir(parents=True, exist_ok=True)
real = Path.home() / ".local/share/meetinginsights"
for d in ("venv", "llama", "models"):
    if (real / d).exists():
        (HOME / d).symlink_to(real / d)

os.environ.update(MEETINGINSIGHTS_HOME=str(HOME), MEETINGINSIGHTS_OUT=str(NOTES), XDG_CONFIG_HOME=str(CFG),
                  LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8", LANGUAGE="en_US")
(CFG / "meetinginsights" / "clients" / "northwind.txt").write_text(
    "Northwind Logistics\nNorthwind, Dock 7, Rivera, SLA tiers, ETA drift, last-mile\n")
(CFG / "meetinginsights" / "config").write_text("notes_model=medium\nwhisper_model=large-v3-turbo\n")

MEETINGS = [
    ("2026-11-10_14-00_pricing-workshop", "Pricing workshop", 47, "Northwind Logistics",
     "Should the entry fee be 8% or 10%?",
     ["Maria Santos and Tom Rivera compared two entry-fee options for the Northwind contract and "
      "agreed to pilot 8% for the first quarter. The SLA tiers stay as drafted, and the last-mile "
      "surcharge is still open."],
     ["The team reviewed the current Northwind price sheet and the gap between the quoted 10% and the 8% discussed last week.",
      "Tom explained that the 8% option only works if ETA drift stays under two percent.",
      "Maria will send the revised proposal with both options before Friday.",
      "The last-mile surcharge was postponed until the pilot data is in."],
     [("Maria", "I'll send the revised proposal with both options before Friday."),
      ("Tom", "Please share the ETA drift report so we can check the two percent limit.")],
     [("Maria", "Let's go with 8% for the first quarter and review it at the end.")],
     [("Tom", "Do we charge the last-mile surcharge during the pilot?")],
     [("Maria", "Thanks everyone for joining, let's start with the price sheet."),
      ("Tom", "Right now Northwind is quoted at 10% entry, but we talked about 8% last week."),
      ("Maria", "Let's go with 8% for the first quarter and review it at the end."),
      ("Tom", "That only works if the ETA drift stays under two percent."),
      ("Maria", "I'll send the revised proposal with both options before Friday."),
      ("Tom", "Do we charge the last-mile surcharge during the pilot?"),
      ("You", "Let's hold that until we have the pilot data."),
      ("Tom", "Please share the ETA drift report so we can check the two percent limit.")]),
    ("2026-11-09_10-30_customer-onboarding", "Customer onboarding sync", 32, "",
     "", ["The onboarding plan for the new warehouse customers was walked through step by step, and the dashboard training was moved to next week."],
     ["Kick-off call with the new customer is set for Thursday.", "Dashboard training moves to next week."],
     [("Priya", "I'll book the training room and send the invite today.")], [("Priya", "We will keep the weekly check-in on Mondays.")], [], 
     [("Priya", "Kick-off with the new customer is on Thursday."), ("You", "Good, I'll prepare the dashboard demo."),
      ("Priya", "I'll book the training room and send the invite today.")]),
    ("2026-11-07_16-00_weekly-sync", "Weekly sync", 21, "", "",
     ["A short weekly status: the carrier integration is on track and two tickets were closed."],
     ["Carrier integration is on track.", "Two support tickets were closed this week."], [], [], [],
     [("You", "Carrier integration is on track."), ("Dev", "Two tickets closed this week.")]),
]


def write(m, live=False):
    name, title, mins, client, focus, overview, summary, actions, decisions, questions, turns = m
    base = f"{name}"
    L = [f"# {title}\n", f"*{mins} minutes · {len(turns)} turns · participants: {', '.join(sorted({t[0] for t in turns}))}*\n"]
    if client:
        L.append(f"> **Client:** {client}\n")
    if focus:
        L.append(f"> **Focus:** {focus}\n")
    L.append("> Notes written offline by a small local model. Structure and speaker attribution are derived "
             "from the transcript itself; only the prose summaries are model-generated.\n")
    L.append("## Summary\n")
    L.append(f"- **{overview[0]}**")
    L += [f"- {s}" for s in summary] + [""]
    if focus:
        L += ["## In focus\n"] + [f"- **{s}** ({i * 1 + 1:02d}:{10 + i * 7:02d}): {t}" for i, (s, t) in
                                enumerate([turns[1][:2], turns[2][:2]])] + [""]
    L += ["## Action Items\n", "| Owner | Action | Time |", "|---|---|---|"]
    L += [f"| {o} | {t} | {i * 4 + 6:02d}:{12 + i * 9:02d} |" for i, (o, t) in enumerate(actions)] if actions else ["_None identified._"]
    L += ["", "## Decisions\n"] + ([f"- **{o}** (08:41): {t}" for o, t in decisions] or ["_None recorded._"]) + [""]
    L += ["## Open Questions\n"] + ([f"- **{o}** (21:05): {t}" for o, t in questions] or ["_None raised._"]) + [""]
    (NOTES / f"{base}.md").write_text("\n".join(L) + "\n")
    (REC / f"{base}.txt").write_text("\n".join(f"[{i * 3:02d}:{(i * 17) % 60:02d}] {s}: {t}" for i, (s, t) in enumerate(turns)) + "\n")
    # newest first in the list: the file stem sorts by date, nothing else to do


for m in MEETINGS:
    write(m)

# ---- a fake CLI for the recording screen: status says "recording", everything else is real
REAL_CLI = ROOT / "bin" / "meetinginsights"
FAKE = TMP / "cli"
FAKE.write_text(f"""#!/bin/bash
if [[ "$1" == status && -f "{TMP}/recording" ]]; then echo 'Recording "Sprint planning" for 12m (live)'; exit 0; fi
if [[ "$1" == slow ]]; then sleep 60; exit 0; fi
exec "{REAL_CLI}" "$@"
""")
FAKE.chmod(0o755)
os.environ["MEETINGINSIGHTS_CLI"] = str(FAKE)

sys.path.insert(0, str(ROOT / "gui")); sys.path.insert(0, str(ROOT / "tests"))
import gi  # noqa: E402
gi.require_version("GdkX11", "3.0")
from gi.repository import GdkX11  # noqa: E402,F401
import meetinginsights_gui as g  # noqa: E402
from test_levels import write_wav  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
app = g.MeetingInsightsApp(); app.register(); app.do_activate()
win = app.get_windows()[0]
win.set_default_size(1180, 900); win.resize(1180, 900)


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.02)


def shot(name, window=None):
    """Grab a window through X11 (run with GDK_BACKEND=x11): Wayland gives no pixels back."""
    pump(1.5)
    xid = (window or win).get_window().get_xid()
    target = OUT / f"{name}.png"
    subprocess.run(["import", "-window", str(xid), str(target)], check=True)
    # drop the pure-black margin the window manager leaves around the window
    subprocess.run(["mogrify", "-fuzz", "3%", "-trim", "+repage", str(target)], check=True)
    print("saved", target, flush=True)


pump(2)
rows = [r for r in win.listbox.get_children() if getattr(r, "path", None)]
win.listbox.select_row(rows[0]); shot("notes")                       # notes of the newest meeting
win.on_new_meeting(); win.client_box.get_child().set_text("Northwind Logistics")
win.focus_entry.set_text("Entry fee: 8% or 10%?"); win.entry.set_text("Pricing workshop"); shot("new-meeting")

# recording screen with meters and a live transcript
(TMP / "recording").write_text("1")
base = REC / "2026-11-10_15-00_sprint-planning"
(HOME / "current").write_text(f"{base}\nSprint planning\n{int(time.time()) - 720}\n")
write_wav(str(base) + ".mic.wav", 9000); write_wav(str(base) + ".sys.wav", 3500)
(base.with_name(base.name + ".partial.txt")).write_text(
    "[00:04] You: Let's start with last sprint's carry-over.\n[00:12] Dev: Two tickets slipped, both blocked on the carrier API.\n"
    "[00:25] You: Okay, can you check with them today?\n[00:31] Dev: I'll email them right after this call.\n")
win.poll_state(); win.mode = "recording"; win.started_at = time.time() - 720
win.set_mode("recording"); win._update_stage(); win._live_text = None
win.show_live(); win._levels_tick(); shot("recording")
(TMP / "recording").unlink(); (HOME / "current").unlink()
win.mode = "idle"; win.set_mode("idle")

# the background queue (a slow fake job keeps it on screen)
win.submit_job("Pricing workshop", ("slow",), lambda r: None)
win.submit_job("Weekly sync", ("slow",), lambda r: None)
win.listbox.select_row(rows[0]); shot("queue")

# settings dialog: open it, grab it, close it
def grab_dialog():
    for w in Gtk.Window.list_toplevels():
        if isinstance(w, Gtk.Dialog) and w.get_visible():
            shot("settings", w)
            w.response(Gtk.ResponseType.CANCEL)
            return False
    return True
GLib.timeout_add(1500, grab_dialog)
win.on_settings()
print("done; temp data in", TMP, flush=True)
os._exit(0)

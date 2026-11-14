"""Join the transcripts of several recordings (parts of one meeting) into a new transcript.

Nothing is changed or removed: the parts are only read, and the result is a new file that is
created without ever replacing an existing one.

- Order is the order given. Part N starts where the previous parts end, so the timeline runs on
  (each recording's own clock restarts at 00:01). The length of a part is its audio length; when
  that is unknown it is estimated from the last spoken line and the start of the next part is
  marked with "~" (approximate), and a warning says so.
- Speaker labels are made unique per part ("Speaker 1 (part 2)"). Diarization numbers voices per
  recording, so "Speaker 1" in part 1 and in part 2 may be different people; the app does not
  guess. To say they are the same person, use `minuta speakers` with 'Old=New'.
- A line "— Part 2: <name> (starts at 12:34) —" marks where each part begins. It is metadata, not
  speech, and never looks like a turn.
- A line that is neither a turn nor blank is kept as written (with a warning); a line that starts
  like a turn ("[12:34] ...") but cannot be read is refused rather than shifted wrongly.
- A transcript that is already a joined meeting is refused: join the original recordings instead.
- A recording that is being recorded or processed right now (a lock held by another job, a live
  transcriber still running) is refused. Locks die with their process, so an abandoned job never
  blocks anything.

Usage: merge.py [--dry-run] <out.txt> <lang> NAME TXT DURATION_SECONDS [NAME TXT DURATION ...]
       merge.py list <notes-dir> <rec-dir>
       (DURATION may be empty: the last timestamp of the part is used)
"""
from __future__ import annotations

import errno
import fcntl
import math
import os
import re
import sys
import tempfile
from pathlib import Path

TURN = re.compile(r"^\[(\d{1,3}):(\d{2})(?::(\d{2}))?\](\s+)([^:\n]+?)(:\s*.*)$")
LOOKS_LIKE_TURN = re.compile(r"^\[\d")
HEADER = re.compile(r"^— (?:Part|Parte) (\d+): (.+) \((?:starts at|começa em) (~?)(\d+:\d{2})\) —$")
_WORDS = {"pt": ("Parte", "começa em", "parte"), "en": ("Part", "starts at", "part")}


class MergeError(Exception):
    """A reason, written for the person using the app, why the parts cannot be joined."""


def _seconds(m: re.Match) -> int:
    if m.group(3) is not None:                       # [h:mm:ss]
        minute, second = int(m.group(2)), int(m.group(3))
        if minute >= 60 or second >= 60:
            raise ValueError("minutes and seconds must be below 60")
        return int(m.group(1)) * 3600 + minute * 60 + second
    second = int(m.group(2))
    if second >= 60:
        raise ValueError("seconds must be below 60")
    return int(m.group(1)) * 60 + second         # [mm:ss]; mm may pass 59 on long meetings


def mmss(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def parse_header(line: str):
    """(index, name, start, approximate) for a part-boundary line, else None."""
    m = HEADER.match(line.strip())
    return (int(m.group(1)), m.group(2), m.group(4), bool(m.group(3))) if m else None


def headers(text: str) -> list[tuple[int, str, str, bool]]:
    return [h for h in (parse_header(ln) for ln in text.splitlines()) if h]


def last_second(text: str) -> int:
    last = 0
    for line in text.splitlines():
        m = TURN.match(line.strip())
        if m:
            last = max(last, _seconds(m))
    return last


def has_turns(text: str) -> bool:
    return any(TURN.match(ln.strip()) for ln in text.splitlines())


def _good_duration(dur) -> float | None:
    try:
        d = float(dur)
    except (TypeError, ValueError):
        return None
    return d if math.isfinite(d) and d > 0 else None


def merge(parts, lang: str = "en"):
    """parts: (name, transcript text, duration in seconds or None).

    Returns (text, plan, warnings); plan is [(name, offset, length, approximate)].
    Raises MergeError for a part that cannot be joined faithfully.
    """
    word, starts, suffix = _WORDS.get(lang, _WORDS["en"])
    out: list[str] = []
    plan: list[tuple[str, int, int, bool]] = []
    warnings: list[str] = []
    offset, prev_approx = 0, False
    for i, (name, text, dur) in enumerate(parts, 1):
        made_of = headers(text)
        if made_of:
            raise MergeError(
                f"{name} is already a joined meeting (made from {', '.join(h[1] for h in made_of)}); "
                "join the original recordings together instead, in one go")
        if not has_turns(text):
            raise MergeError(f"{name}: the transcript has no spoken lines")
        for line_no, line in enumerate(text.splitlines(), 1):
            m = TURN.match(line.strip())
            if m:
                try:
                    _seconds(m)
                except ValueError as e:
                    raise MergeError(f"{name}, line {line_no}: invalid timestamp ({e})") from e
        end = last_second(text) + 1
        known = _good_duration(dur)
        approx = known is None or known < end
        length = end if approx else int(round(known))
        if approx:
            why = "its audio length is unknown" if known is None else "its audio is shorter than its transcript"
            warnings.append(f"{name}: {why}, so its length was estimated from the last spoken line; "
                            "the times of the following parts may be off by the silence at its end")
        plan.append((name, offset, length, prev_approx))
        out.append(f"— {word} {i}: {name} ({starts} {'~' if prev_approx else ''}{mmss(offset)}) —")
        kept = 0
        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            m = TURN.match(s)
            if m:
                label = f"{m.group(5).strip()} ({suffix} {i})"
                out.append(f"[{mmss(_seconds(m) + offset)}]{m.group(4)}{label}{m.group(6)}")
            elif not s:
                continue
            elif LOOKS_LIKE_TURN.match(s):
                raise MergeError(f"{name}, line {n}: it starts like a spoken line but is not in the "
                                 f"'[mm:ss] Speaker: text' form, so its time cannot be shifted: {s[:60]!r}")
            else:
                out.append(s)               # kept exactly as written: nothing is lost
                kept += 1
        if kept:
            warnings.append(f"{name}: {kept} line(s) not in the '[mm:ss] Speaker: text' form were kept "
                            "as written; they are not treated as speech by notes and exports")
        out.append("")
        offset += length
        prev_approx = prev_approx or approx
    return "\n".join(out), plan, warnings


def write_new(path: Path, text: str) -> None:
    """Create `path` with `text` and fail (FileExistsError) rather than replace anything.

    Prefers a hard link from a finished temp file (the new name appears complete or not at all).
    Where hard links are unavailable it creates the name exclusively and removes it again if the
    write fails, so a half-written transcript is never left behind.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.link(tmp, path)
            return
        except FileExistsError:
            raise
        except OSError as e:
            if e.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK, errno.ENOSYS):
                raise
        fd2 = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # FileExistsError if taken
        try:
            with os.fdopen(fd2, "w", encoding="utf-8") as f:
                f.write(text)
        except BaseException:
            try:
                os.unlink(path)              # ours: we just created it exclusively
            except OSError:
                pass
            raise
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# --------------------------------------------------------------- is a recording busy?
def _cmdline(pid: str) -> str:
    try:
        return Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def lock_path(rec_dir: Path, name: str) -> Path:
    return rec_dir / f"{name}.lock"


def _lock_held_elsewhere(rec_dir: Path, name: str) -> bool:
    try:
        fd = os.open(lock_path(rec_dir, name), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)                                  # also drops the lock we may have just taken


def busy_reason_without_lock(rec_dir: Path, name: str) -> str:
    """busy_reason minus the lock test (the caller holds that lock itself)."""
    data = rec_dir.parent
    try:
        first = (data / "current").read_text(encoding="utf-8").splitlines()[0].strip()
        mic = (data / ".mic.pid").read_text().strip()
        if first and Path(first).name == name and "parec" in _cmdline(mic):
            return "it is being recorded right now"
    except (OSError, IndexError, ValueError):
        pass
    try:
        lines = (rec_dir / f"{name}.job").read_text(encoding="utf-8").splitlines()
        if len(lines) > 2 and lines[2].strip().isdigit() and "live_transcribe" in _cmdline(lines[2].strip()):
            return "its live transcription is still running"
    except (OSError, ValueError):
        pass
    return ""


def busy_reason(rec_dir: Path, name: str) -> str:
    """Why the recording must not be touched right now, or '' when it can be."""
    reason = busy_reason_without_lock(rec_dir, name)
    if not reason and _lock_held_elsewhere(rec_dir, name):
        reason = "another Minuta job is processing it right now"
    return reason


def inventory(notes_dir: Path, rec_dir: Path) -> list[tuple[str, str]]:
    """Every recording, as (name, state), newest first.

    state: 'notes' (has notes), 'transcript' (transcript but no notes: invisible in the old list),
    'audio' (audio only, not transcribed yet) or 'busy' (being recorded or processed right now).
    Per-channel capture files and recordings known to be silent are left out.
    """
    names: set[str] = set()
    try:
        for f in (rec_dir.iterdir() if rec_dir.is_dir() else []):
            m = re.match(r"^(.+?)(\.txt|\.wav)$", f.name)
            if m and not re.search(r"\.(mic|sys|partial)$", m.group(1)):
                try:
                    if f.stat().st_size > 0:
                        names.add(m.group(1))
                except OSError:
                    continue
        if notes_dir.is_dir():
            names.update(f.stem for f in notes_dir.glob("*.md"))
    except OSError:
        pass
    out = []
    for n in sorted(names, reverse=True):
        txt = rec_dir / f"{n}.txt"
        if busy_reason(rec_dir, n):
            state = "busy"
        elif (notes_dir / f"{n}.md").is_file():
            state = "notes"
        elif txt.is_file() and txt.stat().st_size > 0:
            state = "transcript"
        elif (rec_dir / f"{n}.nospeech").exists():
            continue
        else:
            state = "audio"
        out.append((n, state))
    return out


def _fail(msg: str, code: int = 1) -> int:
    print(f"merge: {msg}", file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")      # odd file names never crash the report
        except (AttributeError, ValueError):
            pass
    args = argv[1:]
    if args and args[0] == "list":
        if len(args) < 3:
            return _fail("usage: merge.py list <notes-dir> <rec-dir>", 2)
        for name, state in inventory(Path(args[1]), Path(args[2])):
            print(f"{name}\t{state}")
        return 0
    dry = False
    if args and args[0] == "--dry-run":
        dry, args = True, args[1:]
    if len(args) < 5 or (len(args) - 2) % 3:
        print(__doc__, file=sys.stderr)
        return 2
    out, lang, rest = Path(args[0]), args[1], args[2:]
    rec_dir = out.parent
    held, parts = [], []
    try:
        for name, txt, dur in zip(rest[0::3], rest[1::3], rest[2::3]):
            # take the part's lock first (and keep it until we are done): nobody can start
            # rewriting it between the check and the read
            try:
                fd = os.open(lock_path(rec_dir, name), os.O_RDONLY | os.O_CREAT, 0o600)
            except OSError as e:
                return _fail(f"cannot check whether {name} is in use ({e.strerror}); nothing was written")
            held.append(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return _fail(f"{name} is being processed by another Minuta job; wait for it to finish", 5)
            reason = busy_reason_without_lock(rec_dir, name)
            if reason:
                return _fail(f"{name}: {reason}; wait for it to finish", 5)
            try:
                text = Path(txt).read_text(encoding="utf-8")
            except FileNotFoundError:
                return _fail(f"{name} has no transcript yet; process it first "
                             f"(minuta recover, or minuta reprocess {name})")
            except UnicodeDecodeError:
                return _fail(f"the transcript of {name} is not valid UTF-8 text; it was left untouched "
                             "and nothing was written")
            except OSError as e:
                return _fail(f"cannot read the transcript of {name}: {e.strerror}")
            if not text.strip():
                return _fail(f"{name} has an empty transcript; process it first "
                             f"(minuta recover, or minuta reprocess {name})")
            parts.append((name, text, dur))
        try:
            text, plan, warnings = merge(parts, lang)
        except MergeError as e:
            return _fail(str(e))
        for i, (name, off, length, approx) in enumerate(plan, 1):
            print(f"{i}\t{name}\t{'~' if approx else ''}{mmss(off)}\t{mmss(length)}")
        print(f"TOTAL\t{sum(p[2] for p in plan)}")
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        if dry:
            return 0
        try:
            write_new(out, text)
        except FileExistsError:
            return _fail(f"{out.name} already exists; nothing was written", 4)
        except OSError as e:
            return _fail(f"could not write {out.name} ({e.strerror}); nothing was written")
        return 0
    finally:
        for fd in held:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

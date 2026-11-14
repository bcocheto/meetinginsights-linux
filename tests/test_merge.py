"""Joining the parts of a meeting: synthetic data only, in temporary directories."""
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
CLI = str(Path(__file__).resolve().parent.parent / "bin" / "minuta")
sys.path.insert(0, str(LIB))
import merge  # noqa: E402
import notes_local  # noqa: E402
import search  # noqa: E402
import speakers  # noqa: E402

A = "[00:01] Você: bom dia\n[59:30] Participante 1: até já\n"
B = "[00:01] Você: voltamos\n[45:00] Participante 1: fim\n"


class Logic(unittest.TestCase):
    def test_timeline_continues_and_labels_stay_per_part(self):
        text, plan, _w = merge.merge([("a", A, 3600), ("b", B, None)], "en")
        self.assertEqual([(n, o) for n, o, _, _ in plan], [("a", 0), ("b", 3600)])
        self.assertIn("[00:01] Você (part 1): bom dia", text)
        self.assertIn("[60:01] Você (part 2): voltamos", text)
        self.assertIn("— Part 2: b (starts at 60:00) —", text)
        self.assertEqual(merge.headers(text), [(1, "a", "00:00", False), (2, "b", "60:00", False)])
        self.assertNotIn("Você:", text)                      # no bare label that could pass for one person

    def test_duration_never_shorter_than_the_transcript(self):
        _, plan, _w = merge.merge([("a", A, 10), ("b", B, None)], "en")
        self.assertEqual(plan[1][1], 3571)                   # 59:30 + 1s, not 10s

    def test_over_100_minutes_is_still_parsed_by_everything(self):
        text, _, _w = merge.merge([("a", A, 6000), ("b", B, None)], "pt")
        self.assertIn("[100:01] Você (parte 2): voltamos", text)
        self.assertEqual(len(notes_local.parse_turns(text)), 4)
        self.assertEqual(len(speakers.list_speakers(text)), 4)
        self.assertTrue(search.TURN_RE.match("[100:01] x (parte 2): y"))

    def test_speakers_rename_can_unify_explicitly(self):
        text, _, _w = merge.merge([("a", A, None), ("b", B, None)], "en")
        out = speakers.rename_transcript(text, {"Você (part 1)": "Ana", "Você (part 2)": "Ana"})
        self.assertEqual([w for w, _ in speakers.list_speakers(out)][0], "Ana")
        self.assertEqual(dict(speakers.list_speakers(out))["Ana"], 2)

    def test_write_new_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            p.write_text("old")
            with self.assertRaises(FileExistsError):
                merge.write_new(p, "new")
            self.assertEqual(p.read_text(), "old")
            self.assertEqual(os.listdir(d), ["x.txt"])        # no temp file left behind

    def test_inventory_shows_what_was_invisible(self):
        with tempfile.TemporaryDirectory() as d:
            out, rec = Path(d) / "o", Path(d) / "home" / "rec"
            out.mkdir(); rec.mkdir(parents=True)
            (rec / "n.txt").write_text(A); (out / "n.md").write_text("# n")
            (rec / "t.txt").write_text(A)                              # transcript, no notes
            (rec / "w.wav").write_bytes(b"x")                          # audio only
            (rec / "s.wav").write_bytes(b"x"); (rec / "s.nospeech").write_text("")
            (rec / "m.mic.wav").write_bytes(b"x")                      # raw capture
            (rec / "stale.txt").write_text(A); (rec / "stale.txt.new").write_text("x")      # abandoned reprocess
            (rec / "stale.job").write_text("S\n5\n99999999\n")                              # dead live-transcriber pid
            self.assertEqual(dict(merge.inventory(out, rec)), {
                "n": "notes", "t": "transcript", "w": "audio", "stale": "transcript"})

    def test_a_part_that_is_already_joined_is_refused_not_duplicated(self):
        joined, _, _w = merge.merge([("a", A, None), ("b", B, None)], "en")
        with self.assertRaises(merge.MergeError) as cm:
            merge.merge([("m", joined, None), ("c", B, None)], "en")
        self.assertIn("a, b", str(cm.exception))                 # says what it is made of
        self.assertIn("original", str(cm.exception))

    def test_estimated_length_is_flagged_in_the_file_and_warned(self):
        text, plan, warnings = merge.merge([("a", A, None), ("b", B, 100), ("c", B, 100)], "en")
        self.assertTrue(any("estimated" in w and w.startswith("a:") for w in warnings))
        self.assertIn("(starts at ~59:31)", text)                # everything after the estimate is approximate
        self.assertIn("(starts at 00:00)", text)                 # the first part's own start is exact
        self.assertEqual([p[3] for p in plan], [False, True, True])
        text2, _, w2 = merge.merge([("a", A, 4000), ("b", B, 100)], "en")
        self.assertEqual(w2, [w for w in w2 if w.startswith("b:")])
        self.assertNotIn("~", text2.split("— Part 2")[1].splitlines()[0])

    def test_bad_durations_are_estimates_not_crashes(self):
        for bad in (float("nan"), float("inf"), -5, 0, "abc", None):
            text, plan, w = merge.merge([("a", A, bad), ("b", B, None)], "en")
            self.assertTrue(w, bad)
            self.assertEqual(plan[1][1], 3571)

    def test_unrecognised_lines_are_kept_or_refused_never_dropped(self):
        txt = "[00:01] Você: oi\nnota solta escrita à mão\n\n[00:05] Você: fim\n"
        text, _, w = merge.merge([("a", txt, None), ("b", B, None)], "en")
        self.assertIn("nota solta escrita à mão", text)
        self.assertTrue(any("kept as written" in x for x in w))
        self.assertEqual(len(notes_local.parse_turns(text)), 4)  # the loose line is not speech
        with self.assertRaises(merge.MergeError) as cm:
            merge.merge([("a", "[00:01] Você: oi\n[00:05] sem falante\n", None), ("b", B, None)], "en")
        self.assertIn("line 2", str(cm.exception))

    def test_invalid_timestamp_fields_are_refused_with_line_context(self):
        with self.assertRaises(merge.MergeError) as cm:
            merge.merge([("bad", "[00:60] X: invalid\n", None), ("b", B, None)], "en")
        self.assertIn("bad, line 1", str(cm.exception))
        self.assertIn("seconds must be below 60", str(cm.exception))

    def test_write_new_without_hard_links_still_never_overwrites(self):
        import errno
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            with mock.patch("os.link", side_effect=OSError(errno.EPERM, "no links here")):
                merge.write_new(p, "novo")
                self.assertEqual(p.read_text(), "novo")
                with self.assertRaises(FileExistsError):
                    merge.write_new(p, "outro")
            self.assertEqual(p.read_text(), "novo")
            self.assertEqual(os.listdir(d), ["x.txt"])

    def test_failed_write_without_hard_links_leaves_nothing_behind(self):
        import errno
        from unittest import mock
        real = os.fdopen
        calls = []

        def flaky(fd, *a, **k):
            calls.append(fd)
            if len(calls) == 2:                                    # the second write: the exclusive create
                os.close(fd)
                raise OSError(errno.ENOSPC, "disk full")
            return real(fd, *a, **k)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            with mock.patch("os.link", side_effect=OSError(errno.EPERM, "x")), \
                 mock.patch("os.fdopen", side_effect=flaky):
                with self.assertRaises(OSError):
                    merge.write_new(p, "novo")
            self.assertEqual(os.listdir(d), [])

    def test_notes_and_exports_keep_the_boundaries_without_calling_them_speech(self):
        import export
        text, _, _w = merge.merge([("a", A, 3600), ("b", B, None)], "en")
        lines = notes_local.parts_section(text)
        self.assertEqual(lines[0], "## Parts\n")
        self.assertIn("- Part 2: b (starts at 60:00)", lines)
        turns = export.parse_transcript(text)
        self.assertEqual([t["speaker"] for t in turns], ["Você (part 1)", "Participante 1 (part 1)",
                                                         "Você (part 2)", "Participante 1 (part 2)"])
        self.assertEqual([bool(t.get("part")) for t in turns], [True, False, True, False])
        md = export.to_markdown([], turns, "en", True)
        self.assertIn("### Part 2: b (starts at 60:00)", md)
        self.assertNotIn("**Part 2", md)                          # a heading, never a speaker
        same = merge.merge([("a", "[00:01] X: um\n", 10), ("b", "[00:01] X: dois\n", 10)], "en")[0]
        same = same.replace(" (part 2)", " (part 1)")            # even an identical label starts a new section
        self.assertEqual(len(export.group_turns(export.parse_transcript(same))), 2)

    def test_pdf_and_docx_exports_carry_the_boundaries(self):
        try:
            import docx, reportlab  # noqa: F401
        except ImportError:
            self.skipTest("export libraries not installed")
        import export
        text, _, _w = merge.merge([("a", A, 3600), ("b", B, None)], "en")
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.txt"; t.write_text(text)
            for ext in ("docx", "pdf"):
                self.assertEqual(export.main(["-", str(t), str(Path(d) / f"o.{ext}")]), 0)
            body = "\n".join(p.text for p in docx.Document(str(Path(d) / "o.docx")).paragraphs)
            self.assertIn("Part 2: b (starts at 60:00)", body)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.out = t / "home", t / "out"
        (self.home / "rec").mkdir(parents=True); self.out.mkdir()
        self.env = {**os.environ, "MINUTA_HOME": str(self.home), "MINUTA_OUT": str(self.out),
                    "XDG_CONFIG_HOME": str(t / "cfg"), "LC_ALL": "C.UTF-8"}
        self.rec = self.home / "rec"
        (self.rec / "2026-11-10_10-00_a.txt").write_text(A)
        (self.rec / "2026-11-10_10-00_a.wav").write_bytes(b"not really audio")
        (self.out / "2026-11-10_10-00_a.md").write_text("# A\n")
        (self.rec / "2026-11-10_11-30_b.txt").write_text(B)        # transcript without notes
        (self.rec / "2026-11-10_11-30_b.job").write_text("B\n90\n\n")   # leftover marker, as in real life
        (self.rec / "2026-11-10_12-00_c.wav").write_bytes(b"x")    # audio only

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *a):
        return subprocess.run([CLI, *a], capture_output=True, text=True, env=self.env, timeout=60)

    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for d in (self.rec, self.out) for p in d.iterdir() if not p.name.endswith(".lock")}

    def test_parts_lists_the_transcript_without_notes(self):
        got = dict(ln.split("\t") for ln in self.cli("parts").stdout.splitlines())
        self.assertEqual(got, {"2026-11-10_10-00_a": "notes", "2026-11-10_11-30_b": "transcript",
                               "2026-11-10_12-00_c": "audio"})

    def test_merge_creates_a_new_meeting_and_leaves_the_originals_alone(self):
        before = self.snapshot()
        r = self.cli("merge", "--title", "Reunião única", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.snapshot()
        new = {k for k in after if k not in before}
        self.assertEqual(new, {"2026-11-10_10-00_reuniao-unica.txt", "2026-11-10_10-00_reuniao-unica.meta"})
        for k, v in before.items():
            self.assertEqual(after[k], v, k)                       # byte-identical
        txt = (self.rec / "2026-11-10_10-00_reuniao-unica.txt").read_text()
        self.assertLess(txt.index("(part 1)"), txt.index("(part 2)"))
        # and it is now listed, so it cannot disappear from view
        self.assertIn("2026-11-10_10-00_reuniao-unica\ttranscript", self.cli("parts").stdout)
        meta = (self.rec / "2026-11-10_10-00_reuniao-unica.meta").read_text()
        self.assertIn("title=Reunião única", meta)

    def test_order_is_the_order_given(self):
        self.cli("merge", "--title", "Invertida", "--no-notes", "2026-11-10_11-30_b", "2026-11-10_10-00_a")
        txt = (self.rec / "2026-11-10_11-30_invertida.txt").read_text()   # the date prefix comes from the first part given
        self.assertLess(txt.index("voltamos"), txt.index("bom dia"))

    def test_same_title_twice_never_overwrites(self):
        args = ("merge", "--title", "Dup", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(self.cli(*args).returncode, 0)
        first = (self.rec / "2026-11-10_10-00_dup.txt").read_text()
        self.assertEqual(self.cli(*args).returncode, 0)
        self.assertEqual((self.rec / "2026-11-10_10-00_dup.txt").read_text(), first)
        self.assertTrue((self.rec / "2026-11-10_10-00_dup-2.txt").exists())

    def test_merge_does_not_reuse_a_name_with_an_abandoned_job_marker(self):
        marker = self.rec / "2026-11-10_10-00_t.job"
        marker.write_text("Do not overwrite\n")
        r = self.cli("merge", "--title", "T", "--no-notes",
                     "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.rec / "2026-11-10_10-00_t-2.txt").exists())
        self.assertEqual(marker.read_text(), "Do not overwrite\n")

    def test_refusals_write_nothing(self):
        before = self.snapshot()
        a, b = "2026-11-10_10-00_a", "2026-11-10_11-30_b"
        cases = [
            ("--title", "T", "--no-notes", a),                                  # one part
            ("--title", "T", "--no-notes", a, a),                               # same part twice
            ("--no-notes", a, b),                                               # no title
            ("--title", "T", "--no-notes", a, "2026-11-10_12-00_c"),            # audio only: no transcript
            ("--title", "T", "--no-notes", a, "nope"),                          # unknown
            ("--title", "T", "--no-notes", a, "../x"),                          # path tricks
        ]
        for c in cases:
            self.assertNotEqual(self.cli("merge", *c).returncode, 0, c)
        self.assertEqual(self.snapshot(), before)

    def hold_lock(self, name):
        """What a running finish/reprocess does: hold the recording's lock until the process ends."""
        p = subprocess.Popen(["flock", str(self.rec / f"{name}.lock"), "sleep", "30"], start_new_session=True)
        p.kill = lambda: os.killpg(p.pid, 9)                       # flock forks: stop the whole group
        self.addCleanup(lambda: (p.poll() is None) and p.kill())
        for _ in range(100):
            if (self.rec / f"{name}.lock").exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        return p

    def test_a_part_being_processed_is_refused_and_listed_as_busy(self):
        b = "2026-11-10_11-30_b"
        # A stale notes file must not make the GUI show normal editing actions
        # while another job is processing this recording.
        (self.out / f"{b}.md").write_text("# Older notes\n")
        (self.rec / f"{b}.txt.new").write_text("meio caminho")
        p = self.hold_lock(b)
        self.assertEqual(dict(merge.inventory(self.out, self.rec))[b], "busy")
        before = self.snapshot()
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", b)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("another Minuta job", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(f"{b}\tbusy", self.cli("parts").stdout)
        for c in (("reprocess", b, "--notes-only"), ("finish", b), ("delete", b),
                  ("rename", b, "renamed"), ("speakers", b, "Você=Ana")):
            r = self.cli(*c)
            self.assertNotEqual(r.returncode, 0, c)
            self.assertIn("processed", r.stderr)
        self.assertEqual({k: v for k, v in self.snapshot().items() if not k.endswith(".lock")},
                         {k: v for k, v in before.items() if not k.endswith(".lock")})
        p.kill(); p.wait()
        self.assertEqual(self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", b).returncode, 0)

    def test_an_abandoned_job_does_not_block_and_is_still_recoverable(self):
        b = "2026-11-10_11-30_b"
        (self.rec / f"{b}.txt.new").write_text("left by a crash")
        (self.rec / f"{b}.job").write_text("B\n90\n99999999\n")        # the live transcriber is long gone
        self.assertIn(f"{b}\ttranscript", self.cli("parts").stdout)
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", b)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.rec / f"{b}.job").exists())            # recovery data untouched
        self.assertEqual((self.rec / f"{b}.job").read_text(), "B\n90\n99999999\n")

    def test_a_live_transcriber_or_an_active_recording_blocks(self):
        def stop_process(proc):
            if proc.poll() is None:
                proc.kill()
            proc.wait()

        b = "2026-11-10_11-30_b"
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "live_transcribe"])
        self.addCleanup(stop_process, live)
        (self.rec / f"{b}.job").write_text(f"B\n90\n{live.pid}\n")
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", b)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("live transcription", r.stderr)
        live.kill(); live.wait()
        self.assertEqual(self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", b).returncode, 0)
        rec = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "parec"])
        self.addCleanup(stop_process, rec)
        (self.home / ".mic.pid").write_text(str(rec.pid))
        (self.home / "current").write_text(f"{self.rec / b}\nB\n0\n")
        r = self.cli("merge", "--title", "U", "--no-notes", "2026-11-10_10-00_a", b)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("being recorded", r.stderr)

    def test_an_interrupted_recording_is_not_treated_as_active(self):
        (self.home / ".mic.pid").write_text("99999999")
        (self.home / "current").write_text(f"{self.rec / '2026-11-10_11-30_b'}\nB\n0\n")
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_joining_a_joined_meeting_is_refused(self):
        self.cli("merge", "--title", "Um", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        before = self.snapshot()
        r = self.cli("merge", "--title", "Dois", "--no-notes", "2026-11-10_10-00_um", "2026-11-10_11-30_b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already a joined meeting", r.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unreadable_or_odd_transcripts_get_a_clear_message_and_no_file(self):
        (self.rec / "2026-11-10_11-30_b.txt").write_bytes(b"\xff\xfe[00:01] x: y\n")
        before = self.snapshot()
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid UTF-8", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual({k: v for k, v in self.snapshot().items() if not k.endswith(".lock")},
                         {k: v for k, v in before.items() if not k.endswith(".lock")})

    def test_estimate_warning_reaches_the_person(self):
        r = self.cli("merge", "--title", "T", "--no-notes", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertIn("estimated", r.stderr)                  # the .wav here is not real audio

    def test_without_models_it_fails_before_writing_anything(self):
        before = self.snapshot()
        r = self.cli("merge", "--title", "T", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("setup", r.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_writes_nothing(self):
        before = self.snapshot()
        r = self.cli("merge", "--dry-run", "--title", "T", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Would create: 2026-11-10_10-00_t", r.stdout)
        self.assertEqual(self.snapshot(), before)

    def fake_models(self):
        """Stand-ins for the python/llama/model trio, so the notes step can run without any real model."""
        fake = Path(self.tmp.name) / "fakepy"
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$5" "$6" > "$FAKE_LOG"\n[ -n "$FAKE_FAIL" ] && exit 1\necho "# $5" > "$3"\n')
        fake.chmod(0o755)
        llama = Path(self.tmp.name) / "llama"; llama.write_text("#!/bin/sh\n"); llama.chmod(0o755)
        model = Path(self.tmp.name) / "m.gguf"; model.write_bytes(b"GGUF")
        self.log = Path(self.tmp.name) / "log"
        self.env.update(MINUTA_PYTHON=str(fake), MINUTA_LLAMA=str(llama), MINUTA_LLM_MODEL=str(model),
                        FAKE_LOG=str(self.log))

    def test_reprocess_keeps_the_typed_title_and_the_length_of_a_joined_meeting(self):
        self.fake_models()
        r = self.cli("merge", "--title", "Reunião com Ação & Cia", "--no-notes",
                     "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)
        name = "2026-11-10_10-00_reuniao-com-acao-cia"
        r = self.cli("reprocess", name, "--notes-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        title, mins = self.log.read_text().splitlines()
        self.assertEqual(title, "Reunião com Ação & Cia")           # not "reuniao com acao cia"
        self.assertEqual(mins, "104")                               # 59:31 + 45:01, not 0 for "no audio"
        # a rename is remembered too, while there are still no notes
        (self.out / f"{name}.md").unlink()
        self.assertEqual(self.cli("rename", name, "Outro nome").returncode, 0)
        new = "2026-11-10_10-00_outro-nome"
        self.assertEqual(self.cli("reprocess", new, "--notes-only").returncode, 0)
        self.assertEqual(self.log.read_text().splitlines()[0], "Outro nome")

    def test_merge_writes_notes_when_models_are_there_and_keeps_the_transcript_when_they_fail(self):
        self.fake_models()
        r = self.cli("merge", "--title", "Com ata", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log.read_text().splitlines()[0], "Com ata")
        self.assertTrue((self.out / "2026-11-10_10-00_com-ata.md").exists())
        self.env["FAKE_FAIL"] = "1"
        r = self.cli("merge", "--title", "Sem ata", "2026-11-10_10-00_a", "2026-11-10_11-30_b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("reprocess 2026-11-10_10-00_sem-ata --notes-only", r.stderr)
        self.assertTrue((self.rec / "2026-11-10_10-00_sem-ata.txt").exists())
        self.assertIn("2026-11-10_10-00_sem-ata\ttranscript", self.cli("parts").stdout)

    def test_a_pending_recording_keeps_the_title_from_its_job_file(self):
        self.fake_models()
        (self.rec / "2026-11-10_11-30_b.job").write_text("Título digitado\n77\n\n")
        self.assertEqual(self.cli("reprocess", "2026-11-10_11-30_b", "--notes-only").returncode, 0)
        self.assertEqual(self.log.read_text().splitlines()[0], "Título digitado")


if __name__ == "__main__":
    unittest.main()

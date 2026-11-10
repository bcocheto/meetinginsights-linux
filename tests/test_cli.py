"""Command-line behaviour that needs no models: glossaries, interrupted recordings, renames."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

CLI = str(Path(__file__).resolve().parent.parent / "bin" / "minuta")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.out = t / "home", t / "out"
        (self.home / "rec").mkdir(parents=True)
        self.out.mkdir()
        self.env = {**os.environ, "MINUTA_HOME": str(self.home), "MINUTA_OUT": str(self.out),
                    "XDG_CONFIG_HOME": str(t / "cfg"), "LC_ALL": "C.UTF-8"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([CLI, *args], capture_output=True, text=True, env=self.env, timeout=60)

    def test_client_glossary_roundtrip(self):
        self.assertEqual(self.run_cli("client", "set", "Leonardo Barreto", "Be In Rio, uso próprio").returncode, 0)
        self.assertEqual(self.run_cli("client", "list").stdout.strip(), "Leonardo Barreto")
        self.assertIn("Be In Rio", self.run_cli("client", "show", "leonardo barreto").stdout)
        self.assertEqual(self.run_cli("client", "rm", "Leonardo Barreto").returncode, 0)
        self.assertEqual(self.run_cli("client", "list").stdout.strip(), "")
        self.assertNotEqual(self.run_cli("client", "show", "nobody").returncode, 0)

    def test_interrupted_recording_is_reported(self):
        base = self.home / "rec" / "2026-11-10_11-00_queda"
        (self.home / "current").write_text(f"{base}\nQueda\n0\n")
        self.assertIn("Interrupted", self.run_cli("status").stdout)
        self.assertEqual(self.run_cli("recover", "--list").stdout.split(), ["interrupted"])
        r = self.run_cli("start", "novo")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("recover", r.stderr)

    def test_pending_audio_is_listed_until_it_has_notes_or_is_marked_silent(self):
        rec = self.home / "rec"
        (rec / "a.wav").write_bytes(b"x")
        (rec / "b.wav").write_bytes(b"x"); (self.out / "b.md").write_text("# b")
        (rec / "c.wav").write_bytes(b"x"); (rec / "c.nospeech").write_text("")
        (rec / "d.mic.wav").write_bytes(b"x"); (rec / "d.sys.wav").write_bytes(b"x")
        self.assertEqual(sorted(self.run_cli("recover", "--list").stdout.split()), ["pending:a", "pending:d"])

    def test_rename_and_delete_follow_the_meta_file(self):
        rec = self.home / "rec"
        name = "2026-11-10_11-00_antes"
        (self.out / f"{name}.md").write_text("# Antes\n")
        (rec / f"{name}.txt").write_text("[00:01] A: oi\n")
        (rec / f"{name}.meta").write_text("client=X\nfocus=Y\n")
        self.assertEqual(self.run_cli("rename", name, "Depois").returncode, 0)
        self.assertTrue((rec / "2026-11-10_11-00_depois.meta").exists())
        self.assertFalse((rec / f"{name}.meta").exists())
        self.assertEqual(self.run_cli("delete", "2026-11-10_11-00_depois").returncode, 0)
        self.assertFalse((rec / "2026-11-10_11-00_depois.meta").exists())

    def test_speakers_list_and_rename(self):
        name = "2026-11-10_11-00_ata"
        (self.home / "rec" / f"{name}.txt").write_text("[00:01] Speaker 1: oi\n[00:05] You: ola\n")
        (self.out / f"{name}.md").write_text("# Ata\n\n- Speaker 1 abriu.\n")
        self.assertEqual(self.run_cli("speakers", name).stdout.splitlines(), ["Speaker 1\t1", "You\t1"])
        self.assertEqual(self.run_cli("speakers", name, "Speaker 1=Ana").returncode, 0)
        self.assertIn("Ana abriu", (self.out / f"{name}.md").read_text())
        self.assertIn("[00:01] Ana: oi", (self.home / "rec" / f"{name}.txt").read_text())
        self.assertNotEqual(self.run_cli("speakers", name, "Ninguem=Z").returncode, 0)

    def test_search_command(self):
        (self.out / "2026-11-10_11-00_a.md").write_text("# Reunião A\n\n- Preço de entrada: 8%.\n")
        (self.home / "rec" / "2026-11-10_11-00_a.meta").write_text("client=Acme\n")
        r = self.run_cli("search", "preco")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Reunião A", r.stdout); self.assertIn("[Acme]", r.stdout)
        self.assertEqual(self.run_cli("search", "--client", "acme", "entrada").returncode, 0)
        self.assertEqual(self.run_cli("search", "--client", "outro", "entrada").returncode, 1)
        self.assertEqual(self.run_cli("search", "inexistente").returncode, 1)

    def test_obsidian_export_through_the_cli(self):
        name = "2026-11-10_11-00_ata"
        (self.out / f"{name}.md").write_text("# Ata\n\n- **Resumo.**\n")
        vault = Path(self.tmp.name) / "vault"; vault.mkdir()
        self.assertNotEqual(self.run_cli("obsidian", name).returncode, 0)            # no vault yet
        self.assertEqual(self.run_cli("config", "obsidian_vault", str(vault)).returncode, 0)
        self.assertNotEqual(self.run_cli("config", "obsidian_vault", str(vault / "nope")).returncode, 0)
        self.assertNotEqual(self.run_cli("config", "obsidian_folder", "/etc").returncode, 0)
        r = self.run_cli("obsidian", name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((vault / "Meetings" / "2026-11-10 - Ata.md").exists())
        self.assertNotEqual(self.run_cli("obsidian", name, "--folder", "../x").returncode, 0)
        self.run_cli("client", "config", "Acme", "folder", "Clients/Acme")
        self.assertEqual(self.run_cli("client", "config", "Acme").stdout.strip(), "folder=Clients/Acme")
        self.assertNotEqual(self.run_cli("client", "config", "Acme", "folder", "/abs").returncode, 0)

    def test_finish_needs_a_queued_recording(self):
        r = self.run_cli("finish", "2026-11-10_11-00_nada")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nothing to finish", r.stderr)
        self.assertNotEqual(self.run_cli("finish").returncode, 0)

    def test_help_mentions_the_new_commands(self):
        out = self.run_cli("help").stdout
        for word in ("--focus", "client", "recover", "--capture-only", "obsidian"):
            self.assertIn(word, out)


if __name__ == "__main__":
    unittest.main()

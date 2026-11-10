import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import speakers  # noqa: E402

TXT = ("[00:01] Speaker 1: Bom dia, pessoal.\n[00:09] Speaker 2: Bom dia! Speaker 1: não é nome aqui.\n"
       "[00:20] Speaker 1: Vamos começar.\n[01:05] You: Certo.\n")
MD = "# Reunião\n\n- Speaker 1 abriu e Speaker 2 respondeu. Speaker 10 não existe.\n| Speaker 2 | enviar proposta |\n"


class Speakers(unittest.TestCase):
    def test_list_counts_in_order(self):
        self.assertEqual(speakers.list_speakers(TXT), [("Speaker 1", 2), ("Speaker 2", 1), ("You", 1)])

    def test_transcript_changes_only_the_label(self):
        out = speakers.rename_transcript(TXT, {"Speaker 1": "Maria"})
        self.assertIn("[00:01] Maria: Bom dia, pessoal.", out)
        self.assertIn("Speaker 1: não é nome aqui.", out)   # inside the text: untouched
        self.assertEqual(out.count("Maria:"), 2)

    def test_notes_whole_word_and_no_chaining(self):
        out = speakers.rename_notes(MD, {"Speaker 1": "Speaker 2", "Speaker 2": "Tom"})
        self.assertIn("Speaker 2 abriu e Tom respondeu", out)
        self.assertIn("Speaker 10 não existe", out)

    def test_merge_two_voices(self):
        out = speakers.rename_transcript(TXT, {"Speaker 1": "Ana", "Speaker 2": "Ana"})
        self.assertEqual(speakers.list_speakers(out), [("Ana", 3), ("You", 1)])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            t, n = Path(d) / "a.txt", Path(d) / "a.md"
            t.write_text(TXT); n.write_text(MD)
            run = lambda *a: subprocess.run([sys.executable, "-I", str(LIB / "speakers.py"), *a], capture_output=True, text=True)
            self.assertEqual(run("list", str(t)).stdout.splitlines()[0], "Speaker 1\t2")
            self.assertEqual(run("rename", str(t), str(n), "Speaker 2=Tom").returncode, 0)
            self.assertIn("Tom", n.read_text())
            self.assertEqual(run("rename", str(t), str(n), "Ninguem=X").returncode, 1)
            self.assertEqual(run("rename", str(t), str(n), "semigual").returncode, 2)


if __name__ == "__main__":
    unittest.main()

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import obsidian  # noqa: E402

NAME = "2026-11-10_10-05_alinhamento-leonardo"
NOTES = ("# Alinhamento: Leonardo\n\n*11 minutos · 4 falas · participantes: Breno, Leonardo*\n\n"
         "> **Cliente:** Leonardo Barreto\n\n## Resumo\n\n- **Anúncio vira o NS45.**\n- Outro ponto.\n")
TRANSCRIPT = "[00:05] Você: Bom dia.\n[00:09] Leonardo: Fala, Breno.\n"
INDEX = ("---\ntype: indice\nupdated: 2026-11-06\n---\n\n# Reuniões\n\n| Data | Reunião | Tema |\n|---|---|---|\n"
         "| 2026-11-06 | [[Clientes/X/Reuniões/2026-11-06 - Antiga\\|Antiga]] | Tema |\n\n## Fora do escopo\n- nada\n")


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.vault, self.notes, self.rec, self.clients = t / "vault", t / "notes", t / "rec", t / "clients"
        for d in (self.vault, self.notes, self.rec, self.clients):
            d.mkdir()
        (self.notes / f"{NAME}.md").write_text(NOTES)
        (self.rec / f"{NAME}.txt").write_text(TRANSCRIPT)
        (self.rec / f"{NAME}.meta").write_text("client=Leonardo Barreto\nfocus=NS45\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_export(self, **kw):
        kw.setdefault("folder_tpl", "Meetings")
        kw.setdefault("lang", "pt")
        return obsidian.export(NAME, self.notes, self.rec, self.vault, clients_dir=self.clients, **kw)

    def test_note_has_frontmatter_title_and_transcript(self):
        r = self.run_export(folder_tpl="Clientes/{client}/Reuniões")
        path = Path(r["path"])
        self.assertEqual(path.relative_to(self.vault).as_posix(),
                         "Clientes/Leonardo Barreto/Reuniões/2026-11-10 - Alinhamento Leonardo.md")
        text = path.read_text()
        self.assertTrue(text.startswith("---\ntype: reuniao\n"))
        for needle in ('cliente: "Leonardo Barreto"', "participantes: [Breno, Leonardo]", "duration_min: 11",
                       "tags: [reuniao, meetinginsights, leonardo-barreto]", f"meeting: {NAME}",
                       "> [!note]- Transcrição", "> [00:05] Você: Bom dia."):
            self.assertIn(needle, text)

    def test_english_keys_and_no_transcript(self):
        text = Path(self.run_export(lang="en", include_transcript=False)["path"]).read_text()
        self.assertIn("type: meeting", text)
        self.assertIn("participants:", text)
        self.assertNotIn("[!note]", text)

    def test_reexport_updates_the_same_file(self):
        a = self.run_export()["path"]
        (self.notes / f"{NAME}.md").write_text(NOTES + "- Novo.\n")
        b = self.run_export()["path"]
        self.assertEqual(a, b)
        self.assertIn("Novo.", Path(b).read_text())
        self.assertEqual(len(list((self.vault / "Meetings").glob("*.md"))), 1)

    def test_never_overwrites_a_different_note(self):
        a = self.run_export()["path"]
        Path(a).write_text("my own note, no meeting id")
        b = self.run_export()["path"]
        self.assertNotEqual(a, b)
        self.assertEqual(Path(a).read_text(), "my own note, no meeting id")

    def test_refuses_paths_outside_the_vault(self):
        with self.assertRaises(ValueError):
            self.run_export(folder="../fora")
        # an absolute path is read as relative to the vault, so it cannot reach the real /etc
        r = self.run_export(folder="/etc")
        self.assertEqual(Path(r["path"]).relative_to(self.vault).parts[0], "etc")

    def test_hub_and_index_from_the_client_config(self):
        (self.vault / "Hub.md").write_text("# Hub\n")
        idx = self.vault / "Reuniões.md"
        idx.write_text(INDEX)
        (self.clients / "leonardo-barreto.cfg").write_text(
            "folder=Clientes/CA/Reuniões\nhub=Hub\nindex=Reuniões\n")
        r = self.run_export()
        self.assertTrue(r["indexed"])
        self.assertIn("Hub: [[Hub|Leonardo Barreto]]", Path(r["path"]).read_text())
        rows = [ln for ln in idx.read_text().splitlines() if ln.startswith("| 2026-11-10")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].count("|") - rows[0].count("\\|"), 4)         # three columns, like the table
        self.assertIn("updated: ", idx.read_text())
        self.assertNotIn("updated: 2026-11-06", idx.read_text())
        self.assertFalse(self.run_export()["indexed"])                          # not listed twice
        self.assertEqual(len([ln for ln in idx.read_text().splitlines() if ln.startswith("| 2026-11-10")]), 1)

    def test_index_without_a_table_gets_a_bullet(self):
        idx = self.vault / "Lista.md"
        idx.write_text("# Lista\n")
        (self.clients / "leonardo-barreto.cfg").write_text("index=Lista\n")
        self.assertTrue(self.run_export()["indexed"])
        self.assertIn("- 2026-11-10 [[Meetings/2026-11-10 - Alinhamento Leonardo|Alinhamento Leonardo]]", idx.read_text())

    def test_missing_vault_or_notes(self):
        with self.assertRaises(FileNotFoundError):
            obsidian.export(NAME, self.notes, self.rec, self.vault / "nope", "Meetings", self.clients)
        with self.assertRaises(FileNotFoundError):
            obsidian.export("nada", self.notes, self.rec, self.vault, "Meetings", self.clients)


if __name__ == "__main__":
    unittest.main()

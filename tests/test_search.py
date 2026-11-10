import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import search  # noqa: E402


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.notes, self.rec = t / "notes", t / "rec"
        self.notes.mkdir(); self.rec.mkdir()
        self.add("2026-11-10_14-00_pricing-workshop", "# Pricing workshop\n\n- Entry fee of 8% for the pilot.\n",
                 "[00:10] Maria: The last-mile surcharge waits.\n", client="Northwind Logistics")
        self.add("2026-11-09_10-30_onboarding", "# Reunião de onboarding\n\n- Treinamento na quinta.\n",
                 "[00:05] Priya: Vamos agendar a ligação com o cliente.\n")
        self.add("2026-11-07_16-00_weekly", "# Weekly sync\n\n- Carrier integration is on track.\n", "")
        self.meetings = search.load(self.notes, self.rec)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, name, notes, transcript, client=""):
        (self.notes / f"{name}.md").write_text(notes)
        (self.rec / f"{name}.txt").write_text(transcript)
        if client:
            (self.rec / f"{name}.meta").write_text(f"client={client}\nfocus=fee\n")

    def names(self, *a, **k):
        return [h.meeting.name.split("_", 2)[2] for h in search.search(self.meetings, *a, **k)]

    def test_everything_when_the_query_is_empty_newest_first(self):
        self.assertEqual(self.names(), ["pricing-workshop", "onboarding", "weekly"])

    def test_ignores_case_and_accents(self):
        self.assertEqual(self.names("REUNIAO"), ["onboarding"])
        self.assertEqual(self.names("ligacao"), ["onboarding"])

    def test_all_words_must_match(self):
        self.assertEqual(self.names("entry pilot"), ["pricing-workshop"])
        self.assertEqual(self.names("entry onboarding"), [])

    def test_quoted_phrase_must_match_as_written(self):
        self.assertEqual(self.names('"entry fee"'), ["pricing-workshop"])
        self.assertEqual(self.names('"fee entry"'), [])

    def test_finds_text_only_in_the_transcript(self):
        hits = search.search(self.meetings, "surcharge")
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].where.startswith("transcript 00:10"))
        self.assertIn("Maria", hits[0].snippet)

    def test_title_ranks_above_body(self):
        self.add("2026-11-11_09-00_carrier", "# Carrier call\n\n- Nothing else.\n", "")
        self.meetings = search.load(self.notes, self.rec)
        self.assertEqual(self.names("carrier")[0], "carrier")       # in the title beats "weekly" (in the notes)

    def test_client_filter(self):
        self.assertEqual(self.names(client="northwind logistics"), ["pricing-workshop"])
        self.assertEqual(self.names("entry", client="Other"), [])
        self.assertEqual(search.clients(self.meetings), ["Northwind Logistics"])

    def test_snippet_has_no_markdown_noise(self):
        s = search.search(self.meetings, "entry")[0].snippet
        self.assertNotIn("*", s); self.assertNotIn("|", s)

    def test_unbalanced_quote_does_not_crash(self):
        self.assertEqual(self.names('"entry'), ["pricing-workshop"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import notes_external as ext  # noqa: E402
import notes_local as nl  # noqa: E402
from wer import wer  # noqa: E402

TRANSCRIPT = """\
[00:05] Você: Vamos falar do Barão de Jaguaripe, a entrada hoje está em 10% mas combinamos 8%.
[00:20] Participante 1: Eu confirmo que o combinado foi 8% de entrada, vamos ajustar a tabela.
[00:40] Você: Preciso enviar a proposta revisada até sexta-feira.
[01:00] Participante 1: Perfeito, e a Be In Rio entra no funil de lançamento na próxima semana?
[01:10] Você: Bom dia a todos.
"""


class Turns(unittest.TestCase):
    def test_parse(self):
        turns = nl.parse_turns(TRANSCRIPT)
        self.assertEqual(len(turns), 5)
        self.assertEqual(turns[1]["speaker"], "Participante 1")
        self.assertEqual(turns[0]["t"], "00:05")

    def test_classify_portuguese_and_english(self):
        c = lambda t: nl.classify({"text": t})  # noqa: E731
        self.assertEqual(c("Preciso enviar a proposta revisada até sexta-feira."), "action")
        self.assertEqual(c("Você pode me enviar a tabela atualizada hoje?"), "action")
        self.assertEqual(c("Vamos com 8% de entrada no Barão."), "decision")
        self.assertEqual(c("Qual é o valor da entrada hoje?"), "question")
        self.assertEqual(c("I'll send the report tomorrow morning."), "action")
        self.assertEqual(c("Bom dia a todos."), "discussion")

    def test_chunk_keeps_every_turn(self):
        turns = nl.parse_turns(TRANSCRIPT)
        self.assertEqual(sum(len(c) for c in nl.chunk(turns, 80)), len(turns))


class Focus(unittest.TestCase):
    def test_terms_keep_figures(self):
        terms = nl.focus_terms("conflito entre 8% e 10% de entrada")
        self.assertTrue({"8%", "10%", "entrada", "conflito"} <= terms)

    def test_focus_turns_finds_the_relevant_lines(self):
        turns = nl.parse_turns(TRANSCRIPT)
        hits = nl.focus_turns(turns, "conflito entre 8% e 10% de entrada no Barão de Jaguaripe")
        self.assertEqual([t["t"] for t in hits][:2], ["00:05", "00:20"])
        self.assertNotIn("01:10", [t["t"] for t in hits])

    def test_no_focus_no_hits(self):
        self.assertEqual(nl.focus_turns(nl.parse_turns(TRANSCRIPT), ""), [])


class External(unittest.TestCase):
    def test_system_prompt_carries_focus_and_glossary(self):
        p = ext.system_prompt("o conflito 8% vs 10%", "Barão de Jaguaripe, Be In Rio")
        self.assertIn("8% vs 10%", p)
        self.assertIn("Be In Rio", p)
        self.assertEqual(ext.system_prompt(), ext.SYSTEM)

    def test_extract_json_tolerates_fences(self):
        self.assertEqual(ext._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertIsNone(ext._extract_json("sem json"))

    def test_write_notes_rejects_invented_speakers(self):
        turns = nl.parse_turns(TRANSCRIPT)
        reply = ('{"summary": ["ok"], "actions": [{"owner": "Pessoa Inventada", "action": "x", "t": "00:40"}],'
                 ' "decisions": [], "questions": []}')
        fake = mock.Mock(returncode=0, stdout=reply)
        with mock.patch.object(ext, "available", return_value="/bin/claude"), \
             mock.patch.object(ext.subprocess, "run", return_value=fake) as run:
            summaries, buckets = ext.write_notes("claude-code", turns, "foco", "termos")
        self.assertEqual(buckets["action"][0]["speaker"], "—")      # not a real speaker
        self.assertIn("foco", run.call_args[0][0][run.call_args[0][0].index("--system-prompt") + 1])


class Wer(unittest.TestCase):
    def test_wer(self):
        self.assertEqual(wer("a b c d", "a b c d"), 0.0)
        self.assertAlmostEqual(wer("a b c d", "a x c d"), 0.25)
        self.assertEqual(wer("[00:05] Você: um dois", "um dois"), 0.0)


if __name__ == "__main__":
    unittest.main()

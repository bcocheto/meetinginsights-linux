import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import trello  # noqa: E402

KEY, TOKEN = "k" * 32, "t" * 40
LIST_ID = "6af1e3b0b9844f332e542f1e"
NAME = "2026-11-10_14-00_pricing"
NOTES_PT = """# Reunião de preço

## Resumo
- algo

## Itens de ação

| Responsável | Ação | Hora |
|---|---|---|
| Maria | Enviar a proposta revisada até sexta. | 06:12 |
| Tom | Compartilhar o relatório de ETA. | 10:21 |

## Decisões
_Nenhuma registrada._
"""
NOTES_EN = NOTES_PT.replace("Itens de ação", "Action Items").replace("Responsável", "Owner").replace("Ação", "Action").replace("Hora", "Time")


class Fake(BaseHTTPRequestHandler):
    log, fail_after = [], None

    def _answer(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        Fake.log.append({"method": self.command, "path": urlparse(self.path).path, "query": urlparse(self.path).query, "body": body})
        if body.get("token") != TOKEN:
            return self._answer(401, {"message": "invalid token"})
        p = urlparse(self.path).path
        if p == "/members/me":
            return self._answer(200, {"fullName": "Breno Teste", "username": "breno"})
        if p == "/members/me/boards":
            return self._answer(200, [{"id": "b" * 24, "name": "Ideias"}])
        if p.startswith("/boards/") and p.endswith("/lists"):
            return self._answer(200, [{"id": LIST_ID, "name": "Backlog"}])
        if p == "/cards":
            made = sum(1 for r in Fake.log if r["path"] == "/cards")
            if Fake.fail_after is not None and made > Fake.fail_after:
                return self._answer(500, {})
            return self._answer(200, {"id": f"c{made}", "shortUrl": f"https://trello.com/c/card{made}"})
        self._answer(404, {})

    do_GET = do_POST = _handle

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Fake.log, Fake.fail_after = [], None
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.notes, self.rec, self.cfg = t / "notes", t / "rec", t / "cfg"
        for d in (self.notes, self.rec):
            d.mkdir()
        (self.notes / f"{NAME}.md").write_text(NOTES_PT)
        os.environ["MEETINGINSIGHTS_TRELLO_URL"] = self.url
        for k in ("MEETINGINSIGHTS_TRELLO_KEY", "MEETINGINSIGHTS_TRELLO_TOKEN"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.pop("MEETINGINSIGHTS_TRELLO_URL", None)
        self.tmp.cleanup()


class Parsing(unittest.TestCase):
    def test_portuguese_and_english_tables(self):
        for notes in (NOTES_PT, NOTES_EN):
            a = trello.parse_actions(notes)
            self.assertEqual([(x["owner"], x["t"]) for x in a], [("Maria", "06:12"), ("Tom", "10:21")])
            self.assertEqual(a[0]["text"], "Enviar a proposta revisada até sexta." if notes is NOTES_PT else a[0]["text"])

    def test_no_actions(self):
        self.assertEqual(trello.parse_actions("## Action Items\n\n_None identified._\n\n## Decisions\n"), [])

    def test_card_text(self):
        a = trello.parse_actions(NOTES_PT)[0]
        c = trello.card_for(a, NAME, "Reunião de preço")
        self.assertEqual(c["name"], a["text"])
        self.assertIn("Owner: Maria", c["desc"]); self.assertIn("Reunião de preço (2026-11-10 14:00)", c["desc"])


class Api(Base):
    def test_credentials_are_private_and_validated(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        mode = stat.S_IMODE((self.cfg / "trello").stat().st_mode)
        self.assertEqual(mode, 0o600)
        with self.assertRaises(trello.TrelloError):
            trello.save_creds(self.cfg, "short", "x")

    def test_secrets_travel_in_the_body_not_in_the_url(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        trello.boards(self.cfg)
        req = Fake.log[-1]
        self.assertNotIn(TOKEN, req["query"]); self.assertNotIn(KEY, req["query"])
        self.assertEqual(req["body"]["token"], TOKEN)

    def test_boards_and_lists(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        self.assertEqual(trello.boards(self.cfg), [("b" * 24, "Ideias")])
        self.assertEqual(trello.lists(self.cfg, "b" * 24), [(LIST_ID, "Backlog")])
        with self.assertRaises(trello.TrelloError):
            trello.lists(self.cfg, "../../evil")

    def test_bad_token_gives_a_useful_message(self):
        trello.save_creds(self.cfg, KEY, "x" * 40)
        with self.assertRaises(trello.TrelloError) as cm:
            trello.boards(self.cfg)
        self.assertIn("trello login", str(cm.exception))

    def test_not_connected(self):
        with self.assertRaises(trello.TrelloError) as cm:
            trello.boards(self.cfg)
        self.assertIn("not connected", str(cm.exception))

    def test_send_creates_cards_once(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        first = trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID)
        self.assertEqual([r["status"] for r in first], ["created", "created"])
        cards = [r for r in Fake.log if r["path"] == "/cards"]
        self.assertEqual(cards[0]["body"]["idList"], LIST_ID)
        self.assertEqual(cards[0]["body"]["name"], "Enviar a proposta revisada até sexta.")
        again = trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID)
        self.assertEqual([r["status"] for r in again], ["already sent", "already sent"])
        self.assertEqual(len([r for r in Fake.log if r["path"] == "/cards"]), 2)      # nothing new was created

    def test_only_and_dry_run(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        dry = trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID, dry_run=True)
        self.assertEqual([r["status"] for r in dry], ["would create"] * 2)
        self.assertFalse([r for r in Fake.log if r["path"] == "/cards"])
        one = trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID, only={2})
        self.assertEqual([r["i"] for r in one], [2])
        acts = trello.actions_for(NAME, self.notes, self.rec)
        self.assertEqual([bool(a["sent"]) for a in acts], [False, True])

    def test_a_failure_keeps_the_cards_already_made(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        Fake.fail_after = 1
        with self.assertRaises(trello.TrelloError):
            trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID)
        self.assertEqual(sum(1 for a in trello.actions_for(NAME, self.notes, self.rec) if a["sent"]), 1)
        Fake.fail_after = None
        rest = trello.send(NAME, self.notes, self.rec, self.cfg, LIST_ID)
        self.assertEqual([r["status"] for r in rest], ["already sent", "created"])

    def test_needs_a_valid_list(self):
        trello.save_creds(self.cfg, KEY, TOKEN)
        with self.assertRaises(trello.TrelloError):
            trello.send(NAME, self.notes, self.rec, self.cfg, "")


class Cli(Base):
    def run_cli(self, *args, stdin=None):
        env = {**os.environ, "MEETINGINSIGHTS_HOME": str(Path(self.tmp.name) / "home"), "MEETINGINSIGHTS_OUT": str(self.notes),
               "XDG_CONFIG_HOME": str(self.cfg.parent / "xdg")}
        (Path(self.tmp.name) / "home" / "rec").mkdir(parents=True, exist_ok=True)
        env["MEETINGINSIGHTS_HOME"] = str(Path(self.tmp.name) / "home")
        return subprocess.run([str(ROOT / "bin" / "meetinginsights"), *args], capture_output=True, text=True, env=env,
                              input=stdin, timeout=60)

    def test_login_boards_use_and_send(self):
        r = self.run_cli("trello", "login", stdin=f"{KEY}\n{TOKEN}\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Breno Teste", r.stdout)
        cred = Path(self.tmp.name) / "xdg" / "meetinginsights" / "trello"
        self.assertEqual(stat.S_IMODE(cred.stat().st_mode), 0o600)
        self.assertIn("Ideias", self.run_cli("trello", "boards").stdout)
        self.assertEqual(self.run_cli("trello", "lists", "b" * 24).stdout.split("\t")[0], LIST_ID)
        self.assertNotEqual(self.run_cli("trello", "use", "not a list id").returncode, 0)
        self.assertEqual(self.run_cli("trello", "use", LIST_ID, "Backlog").returncode, 0)
        home_rec = Path(self.tmp.name) / "home" / "rec"
        (home_rec / f"{NAME}.txt").write_text("[00:01] A: oi\n")
        acts = json.loads(self.run_cli("trello", "actions", NAME).stdout)
        self.assertEqual(len(acts), 2)
        out = self.run_cli("trello", "send", NAME, "--only", "1")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("created: Enviar a proposta", out.stdout)
        self.assertIn("already sent", self.run_cli("trello", "send", NAME, "--only", "1").stdout)
        self.assertEqual(self.run_cli("trello", "logout").returncode, 0)
        self.assertFalse(cred.exists())


if __name__ == "__main__":
    unittest.main()

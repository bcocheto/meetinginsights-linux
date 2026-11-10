#!/usr/bin/env python3
"""Offline meeting-notes writer backed by a small local GGUF model.

Runs entirely on the machine — no network, no API, no account.

Design: the model is never asked to author the document. Python owns the
structure and all attribution; the model only does two narrow jobs it is
reliable at even at 0.5B — classifying a turn, and paraphrasing a chunk.
Action-item owners come from the transcript's speaker labels (which are exact,
since they come from audio routing), never from the model, so the usual
small-model failure of inventing attendees cannot occur.

Usage: notes_local.py <transcript.txt> <out.md> <model.gguf> [title] [minutes]
"""
import os
import re
import subprocess
import sys
from pathlib import Path

LLAMA_DIR = Path(os.environ.get(
    "MEETINGINSIGHTS_LLAMA_DIR", Path.home() / ".local/share/meetinginsights/llama"))
LLAMA_BIN = LLAMA_DIR / "llama"
THREADS = os.environ.get("MEETINGINSIGHTS_THREADS", "0")
if not THREADS.isdigit() or int(THREADS) < 1:
    THREADS = str(min(os.cpu_count() or 4, 8))


def _ui_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return v.split(".")[0].split("_")[0].split("@")[0].lower()
    return "en"


_PT = {
    "Summary": "Resumo", "Action Items": "Itens de ação", "Decisions": "Decisões",
    "Open Questions": "Perguntas em aberto", "Owner": "Responsável", "Action": "Ação",
    "Time": "Hora", "said": "disse", "minutes": "minutos", "turns": "falas", "participants": "participantes",
    "Could not summarize.": "Não foi possível resumir.",
    "Focus": "Foco", "Client": "Cliente", "In focus": "Em foco",
    "None of the focus points were mentioned.": "Nenhum ponto do foco foi mencionado.",
    "None identified.": "Nenhum identificado.", "None recorded.": "Nenhuma registrada.",
    "None raised.": "Nenhuma levantada.",
    "Notes written by {provider} from the transcript. The transcript was sent to that service.":
        "Ata escrita por {provider} a partir da transcrição. A transcrição foi enviada a esse serviço.",
    "Notes written offline by a small local model. Structure and speaker "
    "attribution are derived from the transcript itself; only the prose "
    "summaries are model-generated.":
        "Ata escrita offline por um modelo local pequeno. A estrutura e a atribuição de falas "
        "vêm da própria transcrição; só os resumos em texto são gerados pelo modelo.",
}


def T(text: str) -> str:
    return _PT.get(text, text) if _ui_lang() == "pt" else text

CLASSES = ("action", "decision", "question", "discussion")


def run_model(model: str, system: str, user: str, n_predict: int, grammar: str | None = None) -> str:
    """One-shot generation via `llama cli -st`. Returns just the model's reply."""
    cmd = [str(LLAMA_BIN), "cli", "--model", model, "-sys", system, "-p", user,
           "-st", "-n", str(n_predict), "-t", THREADS, "--temp", "0.2",
           "-c", "4096", "--no-warmup"]
    if grammar:
        cmd += ["--grammar", grammar]
    env = {"LD_LIBRARY_PATH": str(LLAMA_DIR), "PATH": "/usr/bin:/bin",
           "HOME": str(Path.home()), "TERM": "dumb"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return ""

    # the reply sits between the echoed prompt line ("> ...") and the stats line
    lines, reply, seen = r.stdout.splitlines(), [], False
    for line in lines:
        if not seen:
            if line.startswith("> "):
                seen = True
            continue
        if line.startswith("[ Prompt:") or line.strip() == "Exiting...":
            break
        reply.append(line)
    return "\n".join(reply).strip()


def chat(model: str, system: str, user: str, n_predict: int, grammar=None) -> str:
    return run_model(model, system, user, n_predict, grammar)


def parse_turns(text: str):
    turns = []
    for line in text.splitlines():
        m = re.match(r"\[(\d{2}:\d{2})\]\s+([^:]+):\s*(.*)", line.strip())
        if m:
            turns.append({"t": m.group(1), "speaker": m.group(2).strip(), "text": m.group(3).strip()})
    return turns


def chunk(turns, max_chars=500):
    out, cur, n = [], [], 0
    for t in turns:
        if n + len(t["text"]) > max_chars and cur:
            out.append(cur); cur, n = [], 0
        cur.append(t); n += len(t["text"])
    if cur:
        out.append(cur)
    return out


QUESTION_RE = re.compile(r"\?\s*$")
COMMIT_RE = re.compile(
    r"\b(i will|i\'ll|i am going to|i\'m going to|i can|let me|i shall|"
    r"eu vou|vou (?:enviar|mandar|fazer|ver|checar|verificar|ajustar|preparar|marcar)|"
    r"preciso (?:enviar|mandar|fazer|ver|checar|verificar|ajustar|preparar|marcar)|"
    r"deixa comigo|fico de|eu envio|eu mando|eu faço|eu ajusto)\b", re.I)
REQUEST_RE = re.compile(
    r"\b(can you|could you|please|would you|can we|make sure|"
    r"você pode|voce pode|pode (?:me )?(?:enviar|mandar|fazer|ver|checar|verificar|ajustar)|"
    r"poderia|consegue|por favor|certifique-se)\b", re.I)
DECISION_RE = re.compile(
    r"\b(let us|let\'s|we should|agreed|we will go with|decided|hold off|"
    r"we are going to|going with|sign off|approved|"
    r"vamos (?:com|de|fechar|adotar|seguir|manter|usar)|combinado|fechado|decidimos|"
    r"ficou definido|a gente vai|aprovado|combinamos)\b", re.I)
FILLER_RE = re.compile(
    r"^(hi|hello|morning|good morning|thanks|thank you|ok|okay|right|good|yes|no)\b[\s,.!]*$",
    re.I)


def classify(turn, prev_speaker=None) -> str:
    """Rule-based classification.

    Deliberately not a model call: on this task simple patterns beat a small
    LLM outright (a 0.5B model labelled greetings and questions as actions),
    and rules never hallucinate. The model's judgement is reserved for prose.
    """
    text = turn["text"].strip()
    if FILLER_RE.match(text) or len(text.split()) < 4:
        return "discussion"
    if QUESTION_RE.search(text):
        # "can you raise a ticket?" is a request for action, not an open question
        return "action" if REQUEST_RE.search(text) else "question"
    if COMMIT_RE.search(text):
        return "action"
    if REQUEST_RE.search(text):
        return "action"
    if DECISION_RE.search(text):
        return "decision"
    return "discussion"


def focus_terms(focus: str) -> set[str]:
    """Words and figures worth looking for in the transcript (len >= 4, or containing a digit)."""
    words = re.findall(r"[\w%$.,]+", focus.lower())
    out = {w.strip(".,") for w in words}
    return {w for w in out if len(w) >= 4 or any(c.isdigit() for c in w)}


def focus_turns(turns, focus: str, limit: int = 8):
    """Turns that mention the focus, found by plain keyword matching (no model involved)."""
    terms = focus_terms(focus)
    if not terms:
        return []
    need = 1 if len(terms) < 3 else 2
    hits = []
    for t in turns:
        text = t["text"].lower()
        n = sum(1 for w in terms if w in text)
        if n >= need:
            hits.append((n, t))
    hits.sort(key=lambda x: -x[0])
    return [t for _, t in sorted(hits[:limit], key=lambda x: turns.index(x[1]))]


_PT_HINTS = {"que", "não", "nao", "para", "pra", "com", "uma", "você", "voce", "está", "isso", "então",
             "entao", "também", "vamos", "mas", "como", "ele", "ela", "nós", "gente", "né", "tá", "sim"}
_EN_HINTS = {"the", "and", "is", "that", "we", "you", "this", "with", "for", "it", "are", "have", "will", "of", "to"}


def detect_language(turns) -> str:
    """'Brazilian Portuguese' or 'English', from common words; the summary should match the meeting."""
    words = re.findall(r"[\wÀ-ÿ]+", " ".join(t["text"] for t in turns).lower())
    pt = sum(w in _PT_HINTS for w in words)
    en = sum(w in _EN_HINTS for w in words)
    return "Brazilian Portuguese" if pt > en else "English"


def is_big_model(model: str) -> bool:
    try:
        return Path(model).stat().st_size > 1_000_000_000
    except OSError:
        return False


def overview(model, summaries, language: str, focus: str = "") -> str:
    """Two or three sentences that tie the per-part summaries together (bigger models only)."""
    body = "  ".join(s for _, s in summaries)
    sys_p = (f"Write a short overview of a meeting in {language}, in 2 or 3 sentences, from these "
             "notes of its parts. State the main topic, what was decided or agreed, and what is "
             "left open. Use only what the notes say; do not add names, numbers or facts.")
    if focus:
        sys_p += f" The reader mostly cares about: {focus}."
    out = chat(model, sys_p, body, 160).strip().replace("\n", " ")
    return out if len(out) > 40 else ""


def summarize_chunk(model, turns, focus: str = "", language: str = "") -> str:
    # single line: the CLI echoes the prompt, and a multi-line echo would be
    # mistaken for the model's reply by the output parser
    body = "  ".join(f'{t["speaker"]} {T("said")}: {t["text"]}' for t in turns)
    sys_p = ("Summarize this part of a meeting in ONE factual sentence. "
             "Use only what is stated. Do not add names or facts that are not present.")
    if language:
        sys_p += f" Write the sentence in {language}."
    if focus:
        sys_p += f" The reader mostly cares about: {focus}. Mention it if this part touches it."
    s = chat(model, sys_p, body, 90).strip()
    s = s.split("\n")[0].strip().strip('"')
    return s if len(s) > 15 else ""


def main() -> int:
    transcript, out_path, model = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    title = sys.argv[4] if len(sys.argv) > 4 else "Meeting"
    minutes = sys.argv[5] if len(sys.argv) > 5 else "?"

    turns = parse_turns(transcript.read_text())
    if not turns:
        print("no turns parsed", file=sys.stderr)
        return 3
    speakers = sorted({t["speaker"] for t in turns})
    focus = os.environ.get("MEETINGINSIGHTS_FOCUS", "").strip()
    client = os.environ.get("MEETINGINSIGHTS_CLIENT", "").strip()
    glossary = os.environ.get("MEETINGINSIGHTS_GLOSSARY", "").strip()

    summaries, buckets, used_external = [], None, ""
    provider = os.environ.get("MEETINGINSIGHTS_NOTES_PROVIDER", "local")
    if provider != "local":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import notes_external
        print(f"writing notes with {provider}", file=sys.stderr)
        result = notes_external.write_notes(provider, turns, focus, glossary)
        if result:
            summaries, buckets = result
            used_external = provider
        else:
            print(f"{provider} failed or is not installed; falling back to the local model",
                  file=sys.stderr)

    if buckets is None:
        if not LLAMA_BIN.exists():
            print("llama binary not found", file=sys.stderr)
            return 2
        chunks = chunk(turns)
        language = detect_language(turns)
        print(f"{len(turns)} turns, {len(chunks)} chunks, model={Path(model).name}", file=sys.stderr)
        for i, ch in enumerate(chunks, 1):
            print(f"  summarizing chunk {i}/{len(chunks)}", file=sys.stderr)
            s = summarize_chunk(model, ch, focus, language)
            if s:
                summaries.append((ch[0]["t"], s))
        if len(summaries) >= 2 and is_big_model(model):
            print("  writing the overview", file=sys.stderr)
            ov = overview(model, summaries, language, focus)
            if ov:
                summaries.insert(0, (turns[0]["t"], f"**{ov}**"))
        buckets = {c: [] for c in CLASSES}
        substantive = [t for t in turns if len(t["text"].split()) >= 4]
        for t in substantive:
            buckets[classify(t)].append(t)

    L = []
    L.append(f"# {title}\n")
    L.append(f"*{minutes} {T('minutes')} · {len(turns)} {T('turns')} · {T('participants')}: {', '.join(speakers)}*\n")
    if client:
        L.append(f"> **{T('Client')}:** {client}\n")
    if focus:
        L.append(f"> **{T('Focus')}:** {focus}\n")
    if used_external:
        L.append("> " + T("Notes written by {provider} from the transcript. The transcript was "
                          "sent to that service.").format(provider=used_external) + "\n")
    else:
        L.append("> " + T("Notes written offline by a small local model. Structure and speaker "
                 "attribution are derived from the transcript itself; only the prose "
                 "summaries are model-generated.") + "\n")

    L.append(f"## {T('Summary')}\n")
    L.extend(f"- {s}" for _, s in summaries) if summaries else L.append(f"_{T('Could not summarize.')}_")
    L.append("")

    if focus:
        L.append(f"## {T('In focus')}\n")
        hits = focus_turns(turns, focus)
        L.extend(f'- **{t["speaker"]}** ({t["t"]}): {t["text"]}' for t in hits) if hits \
            else L.append(f"_{T('None of the focus points were mentioned.')}_")
        L.append("")

    L.append(f"## {T('Action Items')}\n")
    if buckets["action"]:
        L.append(f"| {T('Owner')} | {T('Action')} | {T('Time')} |")
        L.append("|---|---|---|")
        for t in buckets["action"]:
            L.append(f'| {t["speaker"]} | {t["text"]} | {t["t"]} |')
    else:
        L.append(f"_{T('None identified.')}_")
    L.append("")

    L.append(f"## {T('Decisions')}\n")
    L.extend(f'- **{t["speaker"]}** ({t["t"]}): {t["text"]}' for t in buckets["decision"]) \
        if buckets["decision"] else L.append(f"_{T('None recorded.')}_")
    L.append("")

    L.append(f"## {T('Open Questions')}\n")
    L.extend(f'- **{t["speaker"]}** ({t["t"]}): {t["text"]}' for t in buckets["question"]) \
        if buckets["question"] else L.append(f"_{T('None raised.')}_")
    L.append("")

    if used_external:
        L.append(f"<!-- mi:provider={used_external} -->")
    out_path.write_text("\n".join(L) + "\n")
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

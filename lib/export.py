#!/usr/bin/env python3
"""Export a meeting (notes + transcript) to Markdown, Word (.docx) or PDF.

Usage: export.py <notes.md> <transcript.txt|-> <out.{md,docx,pdf}> [--no-transcript] [--lang pt|en]

The notes file is the Markdown this program writes itself, so the parser only
has to understand that shape: headings, bullets, one table, a quote and
paragraphs with **bold** / *italic*.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge  # noqa: E402  (part-boundary lines of joined meetings)

ACCENT = "3584E4"
ACCENT_RGB = (0x35, 0x84, 0xE4)
SPEAKER_COLORS = ["3584E4", "26A269", "E5A50A", "C061CB", "E66100", "1C71D8"]

LABELS = {
    "pt": {"transcript": "Transcrição", "exported": "Exportado pelo Minuta", "part": "Parte", "starts": "começa em"},
    "en": {"transcript": "Transcript", "exported": "Exported by Minuta", "part": "Part", "starts": "starts at"},
}


def part_title(part, lang) -> str:
    i, name, start, approx = part
    L = LABELS[lang]
    return f"{L['part']} {i}: {name} ({L['starts']} {'~' if approx else ''}{start})"


# ---------------------------------------------------------------- parsing
def parse_notes(md: str) -> list[tuple]:
    """-> list of ('h1'|'h2'|'quote'|'p', text) | ('ul', [items]) | ('table', [rows])."""
    blocks, ul, table = [], [], []

    def flush():
        nonlocal ul, table
        if ul:
            blocks.append(("ul", ul)); ul = []
        if table:
            blocks.append(("table", table)); table = []

    for raw in md.splitlines():
        s = raw.rstrip()
        if s.lstrip().startswith("<!--"):
            continue
        if re.match(r"^\s*\|.*\|\s*$", s):
            if ul:
                flush()
            if re.match(r"^[\s|:-]+$", s):
                continue
            table.append([c.strip() for c in s.strip().strip("|").split("|")])
            continue
        if table:
            flush()
        if m := re.match(r"^(#{1,3})\s+(.*)", s):
            flush()
            blocks.append(("h1" if len(m.group(1)) == 1 else "h2", m.group(2).strip()))
        elif m := re.match(r"^\s*[-*]\s+(.*)", s):
            ul.append(m.group(1).strip())
        elif s.startswith(">"):
            flush()
            blocks.append(("quote", s.lstrip("> ").strip()))
        elif not s.strip():
            flush()
        else:
            flush()
            blocks.append(("p", s.strip()))
    flush()
    return blocks


def parse_transcript(text: str) -> list[dict]:
    """Turns; the first turn of each joined part also carries 'part': where that recording starts."""
    turns, pending = [], None
    for line in text.splitlines():
        h = merge.parse_header(line)
        if h:
            pending = (h[0], h[1], h[2], h[3])
            continue
        m = re.match(r"\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)", line.strip())
        if m:
            turns.append({"t": m.group(1), "speaker": m.group(2).strip(), "text": m.group(3).strip()})
            if pending:
                turns[-1]["part"] = pending; pending = None
    return turns


def group_turns(turns: list[dict]) -> list[dict]:
    """Merge consecutive lines from the same speaker into one paragraph."""
    out = []
    for t in turns:
        if out and out[-1]["speaker"] == t["speaker"] and not t.get("part"):
            out[-1]["text"] += " " + t["text"]
        else:
            out.append(dict(t))
    return out


def speaker_colors(turns: list[dict]) -> dict[str, str]:
    names = []
    for t in turns:
        if t["speaker"] not in names:
            names.append(t["speaker"])
    return {n: SPEAKER_COLORS[i % len(SPEAKER_COLORS)] for i, n in enumerate(names)}


def split_inline(text: str) -> list[tuple[str, bool, bool]]:
    """'a **b** *c*' -> [('a ', False, False), ('b', True, False), ...]"""
    parts, pos = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*|\*(.+?)\*|_(.+?)_", text):
        if m.start() > pos:
            parts.append((text[pos:m.start()], False, False))
        if m.group(1) is not None:
            parts.append((m.group(1), True, False))
        else:
            parts.append((m.group(2) or m.group(3), False, True))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], False, False))
    return parts or [("", False, False)]


# ---------------------------------------------------------------- markdown
def to_markdown(blocks, turns, lang, with_transcript) -> str:
    L = []
    for kind, val in blocks:
        if kind == "h1":
            L.append(f"# {val}\n")
        elif kind == "h2":
            L.append(f"## {val}\n")
        elif kind == "quote":
            L.append(f"> {val}\n")
        elif kind == "p":
            L.append(val + "\n")
        elif kind == "ul":
            L.extend(f"- {i}" for i in val); L.append("")
        elif kind == "table":
            head, *rows = val
            L.append("| " + " | ".join(head) + " |")
            L.append("|" + "|".join("---" for _ in head) + "|")
            L.extend("| " + " | ".join(r) + " |" for r in rows); L.append("")
    if with_transcript and turns:
        L.append(f"## {LABELS[lang]['transcript']}\n")
        for t in group_turns(turns):
            if t.get("part"):
                L.append(f"### {part_title(t['part'], lang)}\n")
            L.append(f"**{t['speaker']}** · `{t['t']}`  \n{t['text']}\n")
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- docx
def to_docx(blocks, turns, lang, with_transcript, out: Path) -> None:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"; st.font.size = Pt(11)

    def runs(par, text, size=None, color=None, bold_all=False):
        for chunk, b, i in split_inline(text):
            r = par.add_run(chunk)
            r.bold = b or bold_all; r.italic = i
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = RGBColor.from_string(color)

    def shade(cell, fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
        tcPr.append(shd)

    for kind, val in blocks:
        if kind == "h1":
            p = doc.add_paragraph(); runs(p, val, size=22, color="202024", bold_all=True)
        elif kind == "h2":
            p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(14)
            runs(p, val.upper(), size=10, color=ACCENT, bold_all=True)
        elif kind == "quote":
            p = doc.add_paragraph(); p.paragraph_format.left_indent = Pt(10)
            runs(p, val, size=9.5, color="666666")
        elif kind == "p":
            p = doc.add_paragraph(); runs(p, val, color="555555")
        elif kind == "ul":
            for item in val:
                runs(doc.add_paragraph(style="List Bullet"), item)
        elif kind == "table":
            head, *rows = val
            tbl = doc.add_table(rows=1, cols=len(head)); tbl.style = "Table Grid"
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for c, h in zip(tbl.rows[0].cells, head):
                c.text = ""; runs(c.paragraphs[0], h, size=10, color="FFFFFF", bold_all=True); shade(c, ACCENT)
            for r in rows:
                cells = tbl.add_row().cells
                for c, v in zip(cells, r):
                    c.text = ""; runs(c.paragraphs[0], v, size=10)
            doc.add_paragraph()

    if with_transcript and turns:
        p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(18)
        runs(p, LABELS[lang]["transcript"].upper(), size=10, color=ACCENT, bold_all=True)
        colors = speaker_colors(turns)
        for t in group_turns(turns):
            if t.get("part"):
                p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(10)
                runs(p, part_title(t["part"], lang), size=10, color="555555", bold_all=True)
            p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(2)
            r = p.add_run(t["speaker"]); r.bold = True; r.font.color.rgb = RGBColor.from_string(colors[t["speaker"]])
            r = p.add_run(f"   {t['t']}"); r.font.size = Pt(8.5); r.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
            q = doc.add_paragraph(t["text"]); q.paragraph_format.left_indent = Pt(12)
            q.paragraph_format.space_after = Pt(8)
    foot = doc.sections[0].footer.paragraphs[0]
    runs(foot, LABELS[lang]["exported"], size=8, color="999999")
    doc.save(str(out))


# ---------------------------------------------------------------- pdf
def to_pdf(blocks, turns, lang, with_transcript, out: Path) -> None:
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    accent = colors.Color(*(c / 255 for c in ACCENT_RGB))
    grey = colors.Color(0.40, 0.40, 0.42)
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=10.5, leading=15, alignment=TA_LEFT,
                          textColor=colors.Color(0.12, 0.12, 0.14))
    s_h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=22, leading=27, spaceAfter=4)
    s_h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12,
                          textColor=accent, spaceBefore=16, spaceAfter=6)
    s_q = ParagraphStyle("q", parent=base, fontSize=9, leading=13, textColor=grey, leftIndent=8,
                         borderPadding=(4, 4, 4, 8), backColor=colors.Color(0.95, 0.96, 0.98), spaceBefore=6, spaceAfter=6)
    s_meta = ParagraphStyle("m", parent=base, fontSize=9.5, textColor=grey)
    s_cell = ParagraphStyle("c", parent=base, fontSize=9.5, leading=13)
    s_cell_h = ParagraphStyle("ch", parent=s_cell, fontName="Helvetica-Bold", textColor=colors.white)
    s_speaker = ParagraphStyle("sp", parent=base, fontName="Helvetica-Bold", fontSize=10, spaceBefore=8, spaceAfter=1)
    s_text = ParagraphStyle("tx", parent=base, leftIndent=10, spaceAfter=4)
    s_part = ParagraphStyle("pt", parent=base, fontName="Helvetica-Bold", fontSize=9.5, textColor=grey,
                            spaceBefore=12, spaceAfter=2)

    def rich(text):
        out_ = []
        for chunk, b, i in split_inline(text):
            c = escape(chunk)
            out_.append(f"<b>{c}</b>" if b else f"<i>{c}</i>" if i else c)
        return "".join(out_)

    story = []
    for kind, val in blocks:
        if kind == "h1":
            story.append(Paragraph(rich(val), s_h1))
        elif kind == "h2":
            story.append(Paragraph(escape(val.upper()), s_h2))
        elif kind == "quote":
            story.append(Paragraph(rich(val), s_q))
        elif kind == "p":
            story.append(Paragraph(rich(val), s_meta if val.startswith("*") or "·" in val else base))
        elif kind == "ul":
            story.append(ListFlowable([ListItem(Paragraph(rich(i), base), leftIndent=14) for i in val],
                                      bulletType="bullet", bulletColor=accent, leftIndent=14, bulletFontSize=8))
        elif kind == "table":
            head, *rows = val
            data = [[Paragraph(escape(h), s_cell_h) for h in head]] + \
                   [[Paragraph(rich(c), s_cell) for c in r] for r in rows]
            width = A4[0] - 36 * mm
            n = len(head)
            col_w = [width * 0.22, width * 0.66, width * 0.12] if n == 3 else [width / n] * n
            t = Table(data, colWidths=col_w, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), accent),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.96, 0.96, 0.97)]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.Color(0.85, 0.85, 0.88)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story += [Spacer(1, 4), t]

    if with_transcript and turns:
        story.append(Paragraph(escape(LABELS[lang]["transcript"].upper()), s_h2))
        cmap = speaker_colors(turns)
        for t in group_turns(turns):
            if t.get("part"):
                story.append(Paragraph(escape(part_title(t["part"], lang)), s_part))
            hexc = cmap[t["speaker"]]
            head = (f'<font color="#{hexc}">{escape(t["speaker"])}</font>'
                    f'  <font size="8" color="#888888">{escape(t["t"])}</font>')
            story.append(KeepTogether([Paragraph(head, s_speaker), Paragraph(escape(t["text"]), s_text)]))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.Color(0.6, 0.6, 0.62))
        canvas.drawString(18 * mm, 10 * mm, LABELS[lang]["exported"])
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, str(doc_.page))
        canvas.restoreState()

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=18 * mm, bottomMargin=18 * mm,
                      title=next((v for k, v in blocks if k == "h1"), "Meeting")).build(
        story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------- main
def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    with_transcript = "--no-transcript" not in argv
    lang = "en"
    if "--lang" in argv:
        lang = argv[argv.index("--lang") + 1]
        args = [a for a in args if a != lang]
    lang = lang if lang in LABELS else "en"
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    notes, transcript, out = Path(args[0]), args[1], Path(args[2])
    blocks = parse_notes(notes.read_text(encoding="utf-8")) if notes.exists() else []
    turns = parse_transcript(Path(transcript).read_text(encoding="utf-8")) \
        if transcript != "-" and Path(transcript).exists() else []
    if not blocks and not turns:
        print("nothing to export", file=sys.stderr)
        return 3
    ext = out.suffix.lower()
    out.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".md":
        out.write_text(to_markdown(blocks, turns, lang, with_transcript), encoding="utf-8")
    elif ext == ".docx":
        to_docx(blocks, turns, lang, with_transcript, out)
    elif ext == ".pdf":
        to_pdf(blocks, turns, lang, with_transcript, out)
    else:
        print(f"unsupported format: {ext}", file=sys.stderr)
        return 2
    print(f"Exported: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

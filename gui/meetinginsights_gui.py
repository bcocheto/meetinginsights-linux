#!/usr/bin/env python3
"""MeetingInsights — GTK desktop app for on-device meeting recording, transcription and notes.

The UI is a thin layer over the `meetinginsights` CLI: it shells out for start/stop and
reads the resulting markdown from the notes directory. Everything — recording,
transcription and note writing — happens on this machine; nothing is uploaded.
"""
import html
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
try:
    gi.require_version("WebKit2", "4.1")  # Ubuntu 24.04+ / 26.04
except ValueError:
    gi.require_version("WebKit2", "4.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gdk, GLib, Gtk, Notify, Pango, WebKit2  # noqa: E402

# ---------- interface language (follows the OS locale; English fallback) ----------
def _ui_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return v.split(".")[0].split("_")[0].split("@")[0].lower()
    return "en"


UI_LANG = _ui_lang()
STRINGS = {
    "pt": {
        "Language: system default": "Idioma: padrão do sistema",
        "Language: auto-detect": "Idioma: detectar automaticamente",
        "Spoken language of the meeting": "Idioma falado na reunião",
        "Could not save the language": "Não foi possível salvar o idioma",
        "Set up MeetingInsights": "Configurar o MeetingInsights",
        "<b>One-time setup</b>": "<b>Configuração inicial</b>",
        "MeetingInsights needs a speech model and a language model so it can "
        "transcribe and summarise without sending anything to a server.\n\n"
        "This downloads about 1.5 GB once. Everything afterwards runs offline.":
            "O MeetingInsights precisa de um modelo de fala e de um modelo de linguagem para "
            "transcrever e resumir sem enviar nada a um servidor.\n\n"
            "Isso baixa cerca de 1,5 GB uma única vez. Depois, tudo roda offline.",
        "Ready to start": "Pronto para começar",
        "Not now": "Agora não",
        "Download and set up": "Baixar e configurar",
        "Starting…": "Iniciando…",
        "Done": "Concluído",
        "Setup complete.": "Configuração concluída.",
        "Setup did not complete — {detail}": "A configuração não foi concluída — {detail}",
        "Failed": "Falhou",
        "Close": "Fechar",
        "Try again": "Tentar de novo",
        "Private meeting notes, on your device": "Atas de reunião privadas, no seu computador",
        "Reload meetings": "Recarregar reuniões",
        "Meeting title  (e.g. SSO standup)": "Título da reunião  (ex.: Reunião de planejamento)",
        "Idle": "Parado",
        "IDLE": "PARADO",
        "Record": "Gravar",
        "Stop": "Parar",
        "● RECORDING": "● GRAVANDO",
        "Working…": "Processando…",
        "Transcribing…": "Transcrevendo…",
        "Recording started": "Gravação iniciada",
        "Could not start recording": "Não foi possível iniciar a gravação",
        "Notes ready": "Ata pronta",
        "Meeting notes have been written.": "A ata da reunião foi gerada.",
        "Recording processed with errors": "Gravação processada com erros",
        "No meetings yet.\nEnter a title and press Record.":
            "Nenhuma reunião ainda.\nDigite um título e clique em Gravar.",
        "Select a meeting to read its notes.": "Selecione uma reunião para ler a ata.",
        "Could not read notes": "Não foi possível ler a ata",
        "Transcript": "Transcrição",
        "Show full transcript": "Mostrar a transcrição completa",
        "Settings": "Configurações",
        "Transcription model": "Modelo de transcrição",
        "Small — fast (default)": "Small — rápido (padrão)",
        "Medium — more accurate, slower": "Medium — mais preciso, mais lento",
        "Large v3 turbo — most accurate, heaviest": "Large v3 turbo — o mais preciso, o mais pesado",
        "Changing it downloads the model once (up to ~1.5 GB).":
            "Ao trocar, o modelo é baixado uma vez (até ~1,5 GB).",
        "Who writes the notes": "Quem escreve a ata",
        "Local model (private, nothing leaves this computer)":
            "Modelo local (privado, nada sai deste computador)",
        "Claude Code (installed on this computer)": "Claude Code (instalado neste computador)",
        "Gemini CLI (installed on this computer)": "Gemini CLI (instalado neste computador)",
        "not installed": "não instalado",
        "The transcript of each meeting will be sent to that service using your own account.":
            "A transcrição de cada reunião será enviada a esse serviço, usando a sua própria conta.",
        "Save": "Salvar",
        "Could not save the settings": "Não foi possível salvar as configurações",
        "Search meetings…": "Buscar reuniões…",
        "Processor": "Processador",
        "Voices": "Vozes",
        "Tell the people on the call apart by their voice": "Separar as pessoas da chamada pela voz",
        "Splits the other side of the call into Participant 1, 2... Downloads a small model (~46 MB) once.":
            "Divide o outro lado da chamada em Participante 1, 2... Baixa um modelo pequeno (~46 MB) uma vez.",
        "Number of speakers: automatic": "Número de pessoas: automático",
        "Advanced": "Avançado",
        "Initial prompt": "Prompt inicial",
        "Names and terms that appear in your meetings": "Nomes e termos que aparecem nas suas reuniões",
        "Helps the model spell names, products and jargon correctly.":
            "Ajuda o modelo a escrever corretamente nomes, produtos e jargões.",
        "Accuracy": "Precisão",
        "Fast (greedy)": "Rápida (gananciosa)",
        "Balanced (beam search)": "Equilibrada (beam search)",
        "Most accurate (slower)": "Mais precisa (mais lenta)",
        "Even out the volume before transcribing": "Equilibrar o volume antes de transcrever",
        "Processor threads (0 = automatic)": "Threads do processador (0 = automático)",
        "Live transcript": "Transcrição ao vivo",
        "Transcribing as the meeting runs — the rest is written when you press Stop.":
            "Transcrevendo durante a reunião — o restante é escrito quando você clicar em Parar.",
        "Listening. The first lines appear after about a minute of speech.":
            "Ouvindo. As primeiras linhas aparecem depois de cerca de um minuto de fala.",
        "New meeting": "Nova reunião",
        "RECENTS": "RECENTES",
        "Import a file": "Importar arquivo",
        "Drop an audio or video file here": "Solte um arquivo de áudio ou vídeo aqui",
        "or click to browse your files": "ou clique para escolher no computador",
        "More options": "Mais opções",
        "Automatic (use the graphics card when there is one)": "Automático (usa a placa de vídeo, se houver)",
        "CPU only": "Somente CPU",
        "No meetings yet.": "Nenhuma reunião ainda.",
        "Notes by {name}": "Ata por {name}",
        "Written on this computer": "Escrita neste computador",
        "The transcript was sent to that service.": "A transcrição foi enviada a esse serviço.",
        "Nothing left this computer.": "Nada saiu deste computador.",
        "Type a title": "Digite um título",
        "Name the meeting, or leave it blank.": "Dê um nome à reunião, ou deixe em branco.",
        "Press Record": "Clique em Gravar",
        "Use headphones so each voice stays on its own channel.":
            "Use fones de ouvido para cada voz ficar no seu próprio canal.",
        "Press Stop": "Clique em Parar",
        "The transcript and the notes appear here, ready to export.":
            "A transcrição e a ata aparecem aqui, prontas para exportar.",
        "Welcome to MeetingInsights": "Bem-vindo ao MeetingInsights",
        "Record a meeting and get a transcript and notes.": "Grave uma reunião e receba a transcrição e a ata.",
        "Everything runs on this computer unless you choose a cloud service in Settings.":
            "Tudo roda neste computador, a menos que você escolha um serviço na nuvem em Configurações.",
        "Export": "Exportar",
        "Markdown (.md)": "Markdown (.md)",
        "Word (.docx)": "Word (.docx)",
        "PDF (.pdf)": "PDF (.pdf)",
        "Export meeting": "Exportar reunião",
        "Include the transcript": "Incluir a transcrição",
        "Exporting…": "Exportando…",
        "Exported": "Exportado",
        "Could not export": "Não foi possível exportar",
        "Rename": "Renomear",
        "Rewrite notes": "Refazer a ata",
        "Transcribe again": "Transcrever de novo",
        "Edit transcript": "Editar transcrição",
        "Delete": "Excluir",
        "Cancel": "Cancelar",
        "Rename meeting": "Renomear reunião",
        "New title": "Novo título",
        "Delete this meeting?": "Excluir esta reunião?",
        "This permanently deletes the notes, transcript and audio of “{name}”. It cannot be undone.":
            "Isso exclui permanentemente a ata, a transcrição e o áudio de “{name}”. Não dá para desfazer.",
        "Rewriting notes…": "Refazendo a ata…",
        "Transcribing again…": "Transcrevendo de novo…",
        "Deleting…": "Excluindo…",
        "The action failed": "A ação falhou",
        "Could not open the transcript": "Não foi possível abrir a transcrição",
        "Rewrites the notes from the current transcript (use after editing it)":
            "Refaz a ata a partir da transcrição atual (use depois de editá-la)",
        "Transcribes the audio again with the current language and model":
            "Transcreve o áudio de novo com o idioma e o modelo atuais",
    },
}


def T(text: str, **kw) -> str:
    out = STRINGS.get(UI_LANG, {}).get(text, text)
    return out.format(**kw) if kw else out


HOME = Path.home()
NOTES_DIR = Path(os.environ.get("MEETINGINSIGHTS_OUT", HOME / "MeetingNotes"))
DATA_DIR = Path(os.environ.get("MEETINGINSIGHTS_HOME", HOME / ".local/share/meetinginsights"))
LANG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "meetinginsights" / "language"
LANGUAGES = [  # (setting stored in the config file, label)
    ("system", T("Language: system default")),
    ("auto", T("Language: auto-detect")),
    ("pt", "Português"), ("en", "English"), ("es", "Español"),
    ("fr", "Français"), ("de", "Deutsch"), ("it", "Italiano"),
]
REC_DIR = Path(os.environ.get("MEETINGINSIGHTS_HOME", HOME / ".local/share/meetinginsights")) / "rec"
CLI = os.environ.get("MEETINGINSIGHTS_CLI") or shutil.which("meetinginsights") or str(
    Path(__file__).resolve().parent.parent / "bin" / "meetinginsights")

# ---------------------------------------------------------------- theme
# Same visual language as Gavetta: neutral dark surface, GNOME blue accent,
# rounded cards, pill-shaped inputs and chips, hairline borders.
THEME = {
    "bg":            "#1a1a1a",
    "bg_bar":        "#161616",
    "surface":       "rgba(255,255,255,0.05)",
    "surface_hover": "rgba(255,255,255,0.09)",
    "field":         "rgba(255,255,255,0.06)",
    "hairline":      "rgba(255,255,255,0.08)",
    "accent":        "#3584e4",
    "accent_soft":   "#62a0ea",
    "text_primary":  "#ececec",
    "text_secondary":"rgba(255,255,255,0.50)",
    "danger":        "#e01b24",
    "warn":          "#f5c211",
}

CSS = ("""
window, .root { background-color: %(bg)s; color: %(text_primary)s; }
headerbar { background: %(bg_bar)s; border-bottom: 1px solid %(hairline)s; box-shadow: none; color: %(text_primary)s; min-height: 38px; }
headerbar button { border-radius: 999px; background: transparent; border: none; box-shadow: none; color: %(text_secondary)s; }
headerbar button:hover { background: %(surface_hover)s; color: %(text_primary)s; }

/* sidebar: flat, like Vibe */
.sidebar { background: %(bg)s; padding: 14px 8px 4px 8px; }
.sidebar-title { font-size: 16px; font-weight: 700; padding: 2px 10px 10px 10px; }
.section-label { font-size: 10px; font-weight: 600; letter-spacing: 1.3px; color: %(text_secondary)s; padding: 16px 10px 6px 10px; }
button.nav {
  background: transparent; border: none; box-shadow: none; color: %(text_primary)s;
  border-radius: 8px; padding: 8px 10px; font-weight: 500;
}
button.nav:hover { background: %(surface_hover)s; }
separator { background: %(hairline)s; min-width: 1px; min-height: 1px; margin: 0; }

.timer { font-family: monospace; font-size: 26px; font-weight: 300; color: %(text_primary)s; }
.micro { font-size: 10px; font-weight: 700; letter-spacing: 1.2px; color: %(text_secondary)s; }
.status-rec  { color: %(danger)s; }
.status-busy { color: %(accent_soft)s; }
.dim-label { color: %(text_secondary)s; font-size: 12px; }
.dim-icon { color: rgba(255,255,255,0.55); }
.drop-title { font-size: 16px; font-weight: 600; color: %(text_primary)s; }

entry, searchentry {
  background: %(field)s; color: %(text_primary)s; caret-color: %(accent_soft)s;
  border: 1px solid %(hairline)s; border-radius: 999px; padding: 9px 18px;
  font-size: 14px; box-shadow: none;
}
entry:focus, searchentry:focus { border-color: %(accent_soft)s; background: rgba(255,255,255,0.09); }
searchentry { margin: 0 6px 8px 6px; padding: 6px 12px; }

combobox button.combo {
  background: %(field)s; color: %(text_primary)s; border: 1px solid %(hairline)s;
  border-radius: 999px; padding: 7px 16px; box-shadow: none;
}
combobox button.combo:hover { background: %(surface_hover)s; }

button.loud {
  background: %(accent)s; color: #ffffff; border: none; box-shadow: none;
  border-radius: 999px; padding: 10px 34px; font-weight: 700;
}
button.loud:hover { background: %(accent_soft)s; }
button.quiet {
  background: %(surface)s; color: %(text_primary)s;
  border: 1px solid %(hairline)s; border-radius: 999px; box-shadow: none;
  padding: 8px 24px; font-weight: 600;
}
button.quiet:hover { background: %(surface_hover)s; }
button.loud:disabled, button.quiet:disabled {
  background: %(surface)s; color: %(text_secondary)s; border: 1px solid %(hairline)s;
}

/* recents: flat rows */
list, list row { background: transparent; }
list row { margin: 1px 4px; padding: 8px 10px; border-radius: 8px; border: none; }
list row:hover { background: %(surface)s; }
list row:selected { background: %(surface_hover)s; }
.row-title { color: %(text_primary)s; font-weight: 500; }
.row-meta  { color: %(text_secondary)s; font-size: 11px; }
.empty { color: %(text_secondary)s; font-size: 12px; }

/* new-meeting page */
.segment { background: %(surface)s; border: 1px solid %(hairline)s; border-radius: 999px; padding: 3px; }
.segment button {
  background: transparent; border: none; box-shadow: none; border-radius: 999px;
  padding: 7px 20px; color: %(text_secondary)s; font-weight: 600;
}
.segment button:hover { color: %(text_primary)s; }
.segment button.active { background: rgba(255,255,255,0.10); color: %(text_primary)s; }
.dropzone {
  border: 1.5px dashed rgba(255,255,255,0.16); border-radius: 18px; padding: 34px 28px;
}
eventbox:hover .dropzone { border-color: %(accent_soft)s; }

.tag-local, .tag-cloud { font-size: 11px; font-weight: 700; padding: 3px 12px; border-radius: 999px; }
.tag-local { color: #57e389; background: alpha(#57e389, 0.14); }
.tag-cloud { color: #ffa348; background: alpha(#ffa348, 0.16); }

/* action bar: chips */
button.chip {
  padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 700;
  background: %(surface)s; color: rgba(255,255,255,0.75);
  border: none; box-shadow: none;
}
button.chip:hover { background: rgba(255,255,255,0.15); color: #ffffff; }
button.chip.danger:hover { background: alpha(%(danger)s, 0.60); color: #ffffff; }
button.chip:disabled { color: rgba(255,255,255,0.28); }

dialog, messagedialog { background: %(bg)s; color: %(text_primary)s; }
""" % THEME).encode()

NOTE_CSS = """
:root { color-scheme: dark; }
body { background:#1a1a1a; color:#e6e6e8; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       font-size: 14px; line-height: 1.65; padding: 24px 28px; margin:0; }
h1 { font-size: 21px; color:#fff; margin:0 0 4px; }
h2 { font-size: 13px; letter-spacing: .6px; text-transform: uppercase; color: rgba(255,255,255,.55);
     margin: 26px 0 10px; font-weight: 700; }
h3 { font-size: 13.5px; color:#e6e6e8; margin: 16px 0 4px; }
table { border-collapse: separate; border-spacing: 0; width:100%; margin:10px 0; font-size:13px;
        border:1px solid rgba(255,255,255,.08); border-radius:12px; overflow:hidden; }
th { text-align:left; background:rgba(255,255,255,.07); color:rgba(255,255,255,.7); padding:8px 12px; }
td { padding:8px 12px; border-top:1px solid rgba(255,255,255,.06); vertical-align: top; }
code { background:rgba(255,255,255,.08); padding:1px 6px; border-radius:6px; font-size:12.5px; }
blockquote { border-left:3px solid #62a0ea; margin:12px 0; padding:8px 14px; color:rgba(255,255,255,.65);
             background:rgba(255,255,255,.04); border-radius:0 10px 10px 0; }
strong { color:#fff; }
ul,ol { padding-left: 22px; }
li { margin: 4px 0; }
li::marker { color:#62a0ea; }
a { color:#62a0ea; }
pre { background:rgba(255,255,255,.05); border-radius:12px; padding:12px 14px; }
.turn { margin: 0 0 16px; }
.who { font-weight: 700; font-size: 13px; }
.ts { font-weight: 400; font-size: 11px; margin-left: 8px; color: rgba(255,255,255,.38);
      font-variant-numeric: tabular-nums; }
.say { margin: 3px 0 0; padding: 1px 0 1px 12px; border-left: 2px solid var(--c); color: #e6e6e8; }
em { color: rgba(255,255,255,.6); }
"""


SPEAKER_COLORS = ["#62a0ea", "#57e389", "#f5c211", "#dc8add", "#ffa348", "#78aeed"]


def transcript_html(text: str) -> str:
    """The transcript as a conversation: consecutive lines from one speaker are merged."""
    turns = []
    for line in text.splitlines():
        m = re.match(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)", line.strip())
        if not m:
            continue
        t, who, say = m.group(1), m.group(2).strip(), m.group(3).strip()
        if turns and turns[-1][1] == who:
            turns[-1][2] += " " + say
        else:
            turns.append([t, who, say])
    colors, parts = {}, []
    for t, who, say in turns:
        c = colors.setdefault(who, SPEAKER_COLORS[len(colors) % len(SPEAKER_COLORS)])
        parts.append(f'<div class="turn" style="--c:{c}"><div class="who" style="color:{c}">'
                     f'{html.escape(who)}<span class="ts">{t}</span></div>'
                     f'<div class="say">{html.escape(say)}</div></div>')
    return "".join(parts) or f"<pre>{html.escape(text)}</pre>"


PROVIDER_NAMES = {"claude-code": "Claude Code", "gemini-cli": "Gemini CLI"}


def note_provider(md: str) -> str:
    """Which external service wrote these notes ('' when the local model did)."""
    m = re.search(r"<!--\s*mi:provider=([a-z-]+)\s*-->", md)
    return m.group(1) if m else ""


def md_to_html(md: str) -> str:
    """Minimal markdown → HTML. Avoids a hard dependency on the markdown package."""
    try:
        import markdown as _md
        body = _md.markdown(md, extensions=["tables", "fenced_code"])
        return f"<style>{NOTE_CSS}</style>{body}"
    except ImportError:
        pass

    out, in_table, in_list = [], False, False
    for line in md.splitlines():
        s = line.rstrip()
        if s.lstrip().startswith("<!--"):
            continue
        if re.match(r"^\s*\|.*\|\s*$", s):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if re.match(r"^[\s|:-]+$", s):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>"); in_table = True
            out.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>"); in_table = False
        if m := re.match(r"^(#{1,4})\s+(.*)", s):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif m := re.match(r"^\s*[-*]\s+(.*)", s):
            if not in_list: out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
        elif not s.strip():
            if in_list: out.append("</ul>"); in_list = False
        else:
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<p>{inline(s)}</p>")
    if in_list: out.append("</ul>")
    if in_table: out.append("</table>")
    return f"<style>{NOTE_CSS}</style>" + "\n".join(out)


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t



class SetupDialog(Gtk.Dialog):
    """First-run setup: prepares the Python environment and downloads the models.

    The work is done by `meetinginsights setup --porcelain`, which emits
    STEP/PCT/ERR/DONE lines; this dialog only renders them. Keeping the logic in
    the CLI means the terminal and the desktop app cannot drift apart.
    """

    def __init__(self, parent, cli):
        super().__init__(title=T("Set up MeetingInsights"), transient_for=parent, modal=True)
        self.cli = cli
        self.ok = False
        self.proc = None
        self.tail = []
        # Gtk.Dialog.run() returns as soon as any response fires, which would tear
        # the dialog down the instant "Download and set up" is pressed. Drive our
        # own loop instead and close only when the work finishes or is cancelled.
        self.loop = GLib.MainLoop()
        self.connect("destroy", lambda *_: self.loop.quit())
        self.set_default_size(460, -1)
        self.set_deletable(False)

        box = self.get_content_area()
        box.set_spacing(14)
        box.set_margin_top(20); box.set_margin_bottom(16)
        box.set_margin_start(22); box.set_margin_end(22)

        head = Gtk.Label(xalign=0)
        head.set_markup(T("<b>One-time setup</b>"))
        box.pack_start(head, False, False, 0)

        blurb = Gtk.Label(xalign=0, wrap=True)
        blurb.set_text(T(
            "MeetingInsights needs a speech model and a language model so it can "
            "transcribe and summarise without sending anything to a server.\n\n"
            "This downloads about 1.5 GB once. Everything afterwards runs offline."))
        blurb.get_style_context().add_class("dim-label")
        box.pack_start(blurb, False, False, 0)

        self.bar = Gtk.ProgressBar(show_text=True)
        self.bar.set_text(T("Ready to start"))
        self.bar.set_fraction(0.0)
        box.pack_start(self.bar, False, False, 0)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.get_style_context().add_class("micro")
        box.pack_start(self.status, False, False, 0)

        self.cancel_btn = self.add_button(T("Not now"), Gtk.ResponseType.CANCEL)
        self.start_btn = self.add_button(T("Download and set up"), Gtk.ResponseType.OK)
        self.start_btn.get_style_context().add_class("suggested-action")
        self.connect("response", self.on_response)
        self.show_all()

    def on_response(self, _dlg, resp):
        self.stop_emission_by_name("response")
        if resp == Gtk.ResponseType.OK and self.proc is None:
            self.start_btn.set_sensitive(False)
            self.cancel_btn.set_sensitive(False)
            self.bar.set_text(T("Starting…"))
            threading.Thread(target=self._worker, daemon=True).start()
        elif resp == Gtk.ResponseType.CANCEL and self.proc is None:
            self.destroy()

    def _worker(self):
        try:
            self.proc = subprocess.Popen(
                [self.cli, "setup", "--porcelain"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            self.tail = []
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                self.tail = (self.tail + [line])[-4:]
                if "|" not in line:
                    continue
                kind, _, val = line.partition("|")
                GLib.idle_add(self._update, kind, val)
            self.proc.wait()
            GLib.idle_add(self._finish, self.proc.returncode)
        except Exception as e:                      # noqa: BLE001 - surfaced in the dialog
            GLib.idle_add(self._fail, str(e))

    def _update(self, kind, val):
        if kind == "PCT":
            try:
                f = max(0.0, min(1.0, int(val) / 100))
            except ValueError:
                return False
            self.bar.set_fraction(f)
            self.bar.set_text(f"{int(f * 100)}%")
        elif kind == "STEP":
            self.status.set_text(val)
        elif kind == "ERR":
            self._fail(val)
        return False

    def _finish(self, code):
        if code == 0:
            self.ok = True
            self.bar.set_fraction(1.0)
            self.bar.set_text(T("Done"))
            self.status.set_text(T("Setup complete."))
            GLib.timeout_add(700, lambda: (self.destroy(), False)[1])
        else:
            detail = " ".join(getattr(self, "tail", [])) or f"exit code {code}"
            self._fail(T("Setup did not complete — {detail}", detail=detail))
        return False

    def _fail(self, msg):
        self.bar.set_text(T("Failed"))
        self.status.set_text(msg)
        self.cancel_btn.set_label(T("Close"))
        self.cancel_btn.set_sensitive(True)
        self.start_btn.set_label(T("Try again"))
        self.start_btn.set_sensitive(True)
        self.proc = None
        return False


class MeetingInsightsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MeetingInsights")
        self.set_default_size(1120, 720)
        self.busy = False
        self.started_at = None
        self.mode = "idle"
        self.selected = None

        hb = Gtk.HeaderBar(show_close_button=True, title="MeetingInsights")
        self.set_titlebar(hb)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.get_style_context().add_class("root")
        self.add(root)

        # ---- sidebar: title, new meeting, recents, settings
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("sidebar")
        side.set_size_request(270, -1)
        title = Gtk.Label(label="MeetingInsights", xalign=0)
        title.get_style_context().add_class("sidebar-title")
        side.pack_start(title, False, False, 0)
        self.new_btn = Gtk.Button()
        self.new_btn.get_style_context().add_class("nav")
        nb = Gtk.Box(spacing=10)
        nb.pack_start(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU), False, False, 0)
        nb.pack_start(Gtk.Label(label=T("New meeting"), xalign=0), False, False, 0)
        self.new_btn.add(nb)
        self.new_btn.connect("clicked", lambda *_: self.on_new_meeting())
        side.pack_start(self.new_btn, False, False, 0)
        recents = Gtk.Label(label=T("RECENTS"), xalign=0)
        recents.get_style_context().add_class("section-label")
        side.pack_start(recents, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=T("Search meetings…"))
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        side.pack_start(self.search, False, False, 0)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-selected", self.on_select)
        self.listbox.set_filter_func(self._filter_row)
        sw.add(self.listbox)
        side.pack_start(sw, True, True, 0)
        self.settings_btn = Gtk.Button()
        self.settings_btn.get_style_context().add_class("nav")
        sb = Gtk.Box(spacing=10)
        sb.pack_start(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.MENU), False, False, 0)
        sb.pack_start(Gtk.Label(label=T("Settings"), xalign=0), False, False, 0)
        self.settings_btn.add(sb)
        self.settings_btn.connect("clicked", lambda *_: self.on_settings())
        side.pack_start(self.settings_btn, False, False, 6)
        root.pack_start(side, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # ---- stage: "new" (record or import) | "view" (notes, or the live transcript)
        self.stage = Gtk.Stack()
        self.stage.add_named(self._build_new_page(), "new")
        self.webview = WebKit2.WebView()
        self.webview.set_background_color(Gdk.RGBA(0.102, 0.102, 0.102, 1))
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.header = Gtk.Stack()
        self.header.add_named(self._build_actions(), "actions")
        self.header.add_named(self._build_recbar(), "rec")
        view.pack_start(self.header, False, False, 0)
        view.pack_start(self.webview, True, True, 0)
        self.stage.add_named(view, "view")
        root.pack_start(self.stage, True, True, 0)

        self.load_meetings()
        self.poll_state()
        self._update_stage()
        GLib.idle_add(lambda: (self.set_focus(None), False)[1])
        GLib.timeout_add(400, self._first_run_check)
        GLib.timeout_add_seconds(1, self.tick)

    # ---------- the "new meeting" page: record or import ----------
    def _build_new_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        col.set_size_request(520, -1)
        col.set_halign(Gtk.Align.CENTER); col.set_valign(Gtk.Align.CENTER)
        outer.pack_start(col, True, False, 0)

        seg = Gtk.Box(spacing=2)
        seg.get_style_context().add_class("segment")
        seg.set_halign(Gtk.Align.CENTER)
        self.seg_btns = {}
        for key, icon, label in (("record", "audio-input-microphone-symbolic", "Record"),
                                 ("import", "document-open-symbolic", "Import a file")):
            b = Gtk.Button()
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=T(label)), False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _b, k=key: self._set_new_mode(k))
            seg.pack_start(b, False, False, 0)
            self.seg_btns[key] = b
        col.pack_start(seg, False, False, 0)

        self.new_stack = Gtk.Stack()
        # record card
        rec = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        rec.get_style_context().add_class("dropzone")
        mic = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.DIALOG)
        mic.set_pixel_size(40); mic.get_style_context().add_class("dim-icon")
        rec.pack_start(mic, False, False, 0)
        self.entry = Gtk.Entry(placeholder_text=T("Meeting title  (e.g. SSO standup)"))
        self.entry.connect("activate", lambda *_: self.on_record())
        rec.pack_start(self.entry, False, False, 0)
        self.rec_btn = Gtk.Button(label=T("Record"))
        self.rec_btn.get_style_context().add_class("loud")
        self.rec_btn.set_halign(Gtk.Align.CENTER)
        self.rec_btn.connect("clicked", lambda *_: self.on_record())
        rec.pack_start(self.rec_btn, False, False, 0)
        hint = Gtk.Label(label=T("Use headphones so each voice stays on its own channel."))
        hint.get_style_context().add_class("dim-label")
        rec.pack_start(hint, False, False, 0)
        self.new_stack.add_named(rec, "record")
        # import card (click or drop a file)
        imp = Gtk.EventBox()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("dropzone")
        card.set_size_request(-1, 268); card.set_valign(Gtk.Align.CENTER)
        up = Gtk.Image.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.DIALOG)
        up.set_pixel_size(40); up.get_style_context().add_class("dim-icon")
        card.pack_start(up, False, False, 0)
        big = Gtk.Label(label=T("Drop an audio or video file here"))
        big.get_style_context().add_class("drop-title")
        card.pack_start(big, False, False, 0)
        small = Gtk.Label(label=T("or click to browse your files"))
        small.get_style_context().add_class("dim-label")
        card.pack_start(small, False, False, 0)
        imp.add(card)
        imp.connect("button-press-event", lambda *_: self.on_import_pick())
        imp.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        imp.connect("drag-data-received", self._on_drop)
        self.new_stack.add_named(imp, "import")
        col.pack_start(self.new_stack, False, False, 0)

        opts = Gtk.Box(spacing=12)
        opts.set_halign(Gtk.Align.CENTER)
        self.lang_box = Gtk.ComboBoxText()
        self.lang_box.set_tooltip_text(T("Spoken language of the meeting"))
        for key, label in LANGUAGES:
            self.lang_box.append(key, label)
        self.lang_box.set_active_id(self._saved_language())
        self.lang_box.connect("changed", self.on_language_changed)
        opts.pack_start(self.lang_box, False, False, 0)
        more = Gtk.Button(label=T("More options"))
        more.get_style_context().add_class("nav")
        more.connect("clicked", lambda *_: self.on_settings())
        opts.pack_start(more, False, False, 0)
        col.pack_start(opts, False, False, 0)
        self._set_new_mode("record")
        return outer

    def _set_new_mode(self, key):
        self.new_stack.set_visible_child_name(key)
        for k, b in self.seg_btns.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("active")

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        uris = data.get_uris() or []
        if uris:
            try:
                self.import_file(GLib.filename_from_uri(uris[0])[0])
            except (GLib.Error, TypeError):
                pass

    def on_import_pick(self):
        d = Gtk.FileChooserDialog(title=T("Import a file"), transient_for=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Import a file"), Gtk.ResponseType.OK)
        flt = Gtk.FileFilter(); flt.set_name("Audio / video")
        for pat in ("audio/*", "video/*"):
            flt.add_mime_type(pat)
        d.add_filter(flt)
        resp = d.run(); path = d.get_filename(); d.destroy()
        if resp == Gtk.ResponseType.OK and path:
            self.import_file(path)

    def import_file(self, path):
        if self.mode != "idle":
            return
        if not self.is_ready() and not self.run_setup():
            return
        self.set_mode("busy", T("Transcribing…"))

        def work():
            r = self.cli("import", path)
            GLib.idle_add(self._stop_done, r)
        threading.Thread(target=work, daemon=True).start()

    def on_new_meeting(self):
        if self.mode != "idle":
            return
        self.listbox.unselect_all()
        self.selected = None
        self._update_stage()

    def _build_recbar(self):
        bar = Gtk.Box(spacing=14)
        bar.set_margin_top(10); bar.set_margin_bottom(10)
        bar.set_margin_start(18); bar.set_margin_end(18)
        self.status_lbl = Gtk.Label(label=T("Idle"))
        self.status_lbl.get_style_context().add_class("micro")
        bar.pack_start(self.status_lbl, False, False, 0)
        self.timer_lbl = Gtk.Label(label="00:00")
        self.timer_lbl.get_style_context().add_class("timer")
        bar.pack_start(self.timer_lbl, False, False, 0)
        self.stop_btn = Gtk.Button(label=T("Stop"))
        self.stop_btn.get_style_context().add_class("quiet")
        self.stop_btn.set_halign(Gtk.Align.END); self.stop_btn.set_hexpand(True)
        self.stop_btn.connect("clicked", lambda *_: self.on_record())
        bar.pack_start(self.stop_btn, True, True, 0)
        return bar

    def _update_stage(self):
        if self.mode in ("recording", "busy"):
            self.stage.set_visible_child_name("view")
            self.header.set_visible_child_name("rec")
        elif self.selected is not None:
            self.stage.set_visible_child_name("view")
            self.header.set_visible_child_name("actions")
        else:
            self.stage.set_visible_child_name("new")

    @staticmethod
    def _saved_language():
        try:
            value = LANG_FILE.read_text().strip()
        except OSError:
            value = ""
        return value if value in {k for k, _ in LANGUAGES} else "system"

    def on_language_changed(self, combo):
        key = combo.get_active_id()
        if not key:
            return
        try:
            LANG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LANG_FILE.write_text(key + "\n")
        except OSError as e:
            self.error_dialog(T("Could not save the language"), str(e))

    # ---------- live transcript ----------
    def current_base(self):
        """Path prefix of the recording in progress, from the CLI's state file."""
        try:
            first = (DATA_DIR / "current").read_text().splitlines()[0].strip()
            return Path(first) if first else None
        except (OSError, IndexError):
            return None

    def show_live(self):
        base = self.current_base()
        text = ""
        if base:
            try:
                text = Path(str(base) + ".partial.txt").read_text()
            except OSError:
                text = ""
        if text == getattr(self, "_live_text", None):
            return
        self._live_text = text
        if text.strip():
            body = transcript_html(text)
            note = f"<p class='hint'>{html.escape(T('Transcribing as the meeting runs — the rest is written when you press Stop.'))}</p>"
        else:
            body = ""
            note = f"<p class='hint'>{html.escape(T('Listening. The first lines appear after about a minute of speech.'))}</p>"
        self.webview.load_html(
            f"<style>{NOTE_CSS}.hint{{color:rgba(255,255,255,.5);font-style:italic}}</style>"
            f"<h2>{html.escape(T('Live transcript'))}</h2>{note}{body}"
            "<script>window.scrollTo(0, document.body.scrollHeight);</script>", None)

    @staticmethod
    def _split_turn(line):
        m = re.match(r"\[(\d{2}:\d{2})\]\s+([^:]+):\s*(.*)", line.strip())
        return m.groups() if m else ("", "", line.strip())

    # ---------- first run ----------
    def is_ready(self):
        """`meetinginsights ready` exits non-zero until setup has been run."""
        try:
            return self.cli("ready").returncode == 0
        except Exception:
            return False

    def _first_run_check(self, force=False):
        if self.is_ready():
            return False
        self.run_setup()
        return False

    def run_setup(self):
        dlg = SetupDialog(self, CLI)
        dlg.show_all()
        dlg.loop.run()                 # returns when the dialog is destroyed
        ready = dlg.ok
        if ready:
            self.load_meetings()
        return ready

    # ---------- state ----------
    def cli(self, *args):
        return subprocess.run([CLI, *args], capture_output=True, text=True, timeout=900)

    def poll_state(self):
        r = self.cli("status")
        recording = "Recording" in r.stdout
        self.set_mode("recording" if recording else "idle")
        if recording:
            m = re.search(r"for (\d+)m", r.stdout)
            self.started_at = time.time() - (int(m.group(1)) * 60 if m else 0)
            t = re.search(r'Recording "(.+?)"', r.stdout)
            if t:
                self.entry.set_text(t.group(1))

    def set_mode(self, mode, note=""):
        ctx = self.status_lbl.get_style_context()
        for c in ("status-rec", "status-busy"):
            ctx.remove_class(c)
        self.mode = mode
        self.lang_box.set_sensitive(mode == "idle")
        if mode == "recording":
            self.status_lbl.set_text(T("● RECORDING")); ctx.add_class("status-rec")
            self.stop_btn.set_label(T("Stop")); self.stop_btn.set_sensitive(True)
            self.entry.set_sensitive(False); self.rec_btn.set_sensitive(False)
        elif mode == "busy":
            self.status_lbl.set_text(note or T("Working…")); ctx.add_class("status-busy")
            self.stop_btn.set_label(T("Working…")); self.stop_btn.set_sensitive(False)
            self.entry.set_sensitive(False); self.rec_btn.set_sensitive(False)
        else:
            self.status_lbl.set_text(T("IDLE"))
            self.rec_btn.set_sensitive(True); self.entry.set_sensitive(True)
            self.timer_lbl.set_text("00:00"); self.started_at = None
        self._refresh_actions()
        self._update_stage()

    def tick(self):
        # reconcile with the CLI every 5s so the UI stays correct when the
        # recording is started or stopped from a terminal (or dies on its own)
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self.mode != "busy" and self._ticks % 5 == 0:
            try:
                live = "Recording" in self.cli("status").stdout
            except Exception:
                live = self.mode == "recording"
            if live and self.mode == "idle":
                self.poll_state()
            elif not live and self.mode == "recording":
                self.set_mode("idle")
                self.load_meetings()
        if self.mode == "recording":
            self.show_live()
        if self.mode == "recording" and self.started_at:
            e = int(time.time() - self.started_at)
            self.timer_lbl.set_text(f"{e//3600:02d}:{(e%3600)//60:02d}:{e%60:02d}"
                                    if e >= 3600 else f"{e//60:02d}:{e%60:02d}")
        return True

    # ---------- actions ----------
    def on_record(self):
        if self.mode == "recording":
            self.set_mode("busy", T("Transcribing…"))
            threading.Thread(target=self._stop_worker, daemon=True).start()
        elif self.mode == "idle":
            if not self.is_ready() and not self.run_setup():
                return
            title = self.entry.get_text().strip() or "meeting"
            r = self.cli("start", title)
            if r.returncode == 0:
                self.started_at = time.time()
                self.set_mode("recording")
                self.notify(T("Recording started"), title)
            else:
                self.error_dialog(T("Could not start recording"), r.stderr or r.stdout)

    def _stop_worker(self):
        r = self.cli("stop")
        GLib.idle_add(self._stop_done, r)

    def _stop_done(self, r):
        self.set_mode("idle")
        self._live_text = None
        self.load_meetings()
        if r.returncode == 0:
            self.notify(T("Notes ready"), T("Meeting notes have been written."))
            if self.listbox.get_row_at_index(0):
                self.listbox.select_row(self.listbox.get_row_at_index(0))
        else:
            self.error_dialog(T("Recording processed with errors"), (r.stderr or r.stdout)[-800:])
        return False

    # ---------- meetings ----------
    def load_meetings(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        files = sorted(NOTES_DIR.glob("*.md"), reverse=True) if NOTES_DIR.exists() else []
        if not files:
            row = Gtk.ListBoxRow(selectable=False)
            lbl = Gtk.Label(label=T("No meetings yet."))
            lbl.get_style_context().add_class("empty")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_margin_top(20)
            row.add(lbl); self.listbox.add(row); self.listbox.show_all()
            return
        for f in files:
            self.listbox.add(self._meeting_row(f))
        self.listbox.show_all()

    def _show_provider(self, provider):
        ctx = self.provider_lbl.get_style_context()
        for c in ("tag-local", "tag-cloud"):
            ctx.remove_class(c)
        if not provider and self.selected is None:
            self.provider_lbl.set_text(""); return
        if provider:
            ctx.add_class("tag-cloud")
            self.provider_lbl.set_text("☁  " + T("Notes by {name}", name=PROVIDER_NAMES.get(provider, provider)))
            self.provider_lbl.set_tooltip_text(T("The transcript was sent to that service."))
        else:
            ctx.add_class("tag-local")
            self.provider_lbl.set_text("●  " + T("Written on this computer"))
            self.provider_lbl.set_tooltip_text(T("Nothing left this computer."))

    def _filter_row(self, row):
        q = self.search.get_text().strip().lower()
        if not q or not hasattr(row, "path"):
            return True
        if q in row.path.stem.lower().replace("-", " ").replace("_", " "):
            return True
        try:
            return q in row.path.read_text().lower()
        except OSError:
            return False

    def _meeting_row(self, path: Path):
        stem = path.stem
        m = re.match(r"(\d{4}-\d{2}-\d{2})[_-](\d{2})-(\d{2})_(.*)", stem)
        if m:
            date, hh, mm, slug = m.groups()
            title = slug.replace("-", " ").title()
            meta = f"{date}  ·  {hh}:{mm}"
        elif (m2 := re.match(r"(\d{4}-\d{2}-\d{2})_(.*)", stem)):
            title = m2.group(2).replace("-", " ").replace("_", " ").title()
            meta = m2.group(1)
        else:
            title, meta = stem.replace("-", " ").title(), ""
        try:
            with path.open(encoding="utf-8") as fh:
                heading = fh.readline().strip()
            if heading.startswith("# ") and len(heading) > 2:
                title = heading[2:].strip()
        except OSError:
            pass
        try:
            prov = note_provider(path.read_text(encoding="utf-8"))
        except OSError:
            prov = ""
        if prov:
            meta += "  ·  ☁ " + PROVIDER_NAMES.get(prov, prov)
        row = Gtk.ListBoxRow()
        row.path = path
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        badge = Gtk.Box()
        badge.get_style_context().add_class("badge")
        icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic", Gtk.IconSize.BUTTON)
        icon.set_hexpand(True); icon.set_halign(Gtk.Align.CENTER); icon.set_valign(Gtk.Align.CENTER)
        badge.pack_start(icon, True, True, 0)
        badge.set_valign(Gtk.Align.CENTER); badge.set_halign(Gtk.Align.START); badge.set_hexpand(False)
        outer.pack_start(badge, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        outer.pack_start(box, True, True, 0)
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("row-title")
        t.set_ellipsize(Pango.EllipsizeMode.END)
        d = Gtk.Label(label=meta, xalign=0)
        d.get_style_context().add_class("row-meta")
        box.pack_start(t, False, False, 0); box.pack_start(d, False, False, 0)
        row.add(outer)
        return row

    def on_select(self, _lb, row):
        if not row or not hasattr(row, "path"):
            self.selected = None
            self._refresh_actions()
            self._show_provider("")
            self._update_stage()
            return
        self.selected = row.path
        if self.mode != "idle":          # keep the live transcript on screen
            return
        self._refresh_actions()
        self._update_stage()
        try:
            md = row.path.read_text()
        except OSError as e:
            md = f"# {T('Could not read notes')}\n\n{e}"
        self._show_provider(note_provider(md))
        transcript = REC_DIR / (row.path.stem + ".txt")
        html_doc = md_to_html(md)
        if transcript.exists():
            html_doc += f"<h2>{T('Transcript')}</h2>" + transcript_html(transcript.read_text())
        self.webview.load_html(html_doc, None)

    def _build_actions(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(8); bar.set_margin_bottom(8)
        bar.set_margin_start(16); bar.set_margin_end(16)
        self.action_btns = []
        spec = [
            ("Rename", None, self.on_rename),
            ("Rewrite notes", "Rewrites the notes from the current transcript (use after editing it)", self.on_rewrite),
            ("Transcribe again", "Transcribes the audio again with the current language and model", self.on_retranscribe),
            ("Edit transcript", None, self.on_edit_transcript),
            ("Export", None, self.on_export_menu),
            ("Delete", None, self.on_delete),
        ]
        for label, tip, handler in spec:
            b = Gtk.Button(label=T(label))
            if tip:
                b.set_tooltip_text(T(tip))
            b.get_style_context().add_class("chip")
            if label == "Delete":
                b.get_style_context().add_class("danger")
                bar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
            b.connect("clicked", lambda _b, h=handler: h())
            b.set_sensitive(False)
            bar.pack_start(b, False, False, 0)
            self.action_btns.append(b)
        self.provider_lbl = Gtk.Label(label="")
        self.provider_lbl.set_halign(Gtk.Align.END); self.provider_lbl.set_hexpand(True)
        bar.pack_start(self.provider_lbl, True, True, 0)
        return bar

    def _refresh_actions(self):
        enabled = self.selected is not None and getattr(self, "mode", "idle") == "idle"
        for b in self.action_btns:
            b.set_sensitive(enabled)

    def _run_action(self, busy_text, *args, then_select=None):
        self.set_mode("busy", T(busy_text))

        def work():
            r = self.cli(*args)
            GLib.idle_add(self._action_done, r, then_select)
        threading.Thread(target=work, daemon=True).start()

    def _action_done(self, r, then_select):
        self.set_mode("idle")
        if r.returncode != 0:
            self.error_dialog(T("The action failed"), (r.stderr or r.stdout)[-800:])
        keep = then_select
        if keep == "__renamed__":
            m = re.search(r"Renamed to: (\S+)", r.stdout)
            keep = m.group(1) if m else (self.selected.stem if self.selected else None)
        self.selected = None
        self.load_meetings()
        if keep:
            for row in self.listbox.get_children():
                if getattr(row, "path", None) and row.path.stem == keep:
                    self.listbox.select_row(row)
                    break
        self._refresh_actions()
        return False

    def on_rename(self):
        if not self.selected:
            return
        d = Gtk.Dialog(title=T("Rename meeting"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Rename"), Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_margin_top(12); box.set_margin_start(16); box.set_margin_end(16); box.set_margin_bottom(8)
        entry = Gtk.Entry(placeholder_text=T("New title"), activates_default=True)
        entry.set_width_chars(36)
        box.pack_start(entry, False, False, 0)
        d.show_all()
        resp = d.run()
        new = entry.get_text().strip()
        d.destroy()
        if resp == Gtk.ResponseType.OK and new:
            self._run_action("Working…", "rename", self.selected.stem, new, then_select="__renamed__")

    def on_rewrite(self):
        if self.selected:
            self._run_action("Rewriting notes…", "reprocess", self.selected.stem, "--notes-only",
                             then_select=self.selected.stem)

    def on_retranscribe(self):
        if self.selected:
            self._run_action("Transcribing again…", "reprocess", self.selected.stem,
                             then_select=self.selected.stem)

    def on_edit_transcript(self):
        if not self.selected:
            return
        txt = REC_DIR / (self.selected.stem + ".txt")
        try:
            subprocess.Popen(["xdg-open", str(txt)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.error_dialog(T("Could not open the transcript"), str(e))

    def on_export_menu(self):
        if not self.selected:
            return
        menu = Gtk.Menu()
        for ext, label in (("pdf", "PDF (.pdf)"), ("docx", "Word (.docx)"), ("md", "Markdown (.md)")):
            item = Gtk.MenuItem(label=T(label))
            item.connect("activate", lambda _i, e=ext: self.on_export(e))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(self.action_btns[4], Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def on_export(self, ext):
        if not self.selected:
            return
        name = self.selected.stem
        d = Gtk.FileChooserDialog(title=T("Export meeting"), transient_for=self,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Export"), Gtk.ResponseType.OK)
        d.set_do_overwrite_confirmation(True)
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or str(HOME)
        d.set_current_folder(docs)
        d.set_current_name(f"{name}.{ext}")
        with_t = Gtk.CheckButton(label=T("Include the transcript"), active=True)
        with_t.show()
        d.set_extra_widget(with_t)
        resp = d.run()
        dest = d.get_filename()
        include = with_t.get_active()
        d.destroy()
        if resp != Gtk.ResponseType.OK or not dest:
            return
        if not dest.lower().endswith("." + ext):
            dest += "." + ext
        args = ["export", name, ext, dest] + ([] if include else ["--no-transcript"])
        self.set_mode("busy", T("Exporting…"))

        def work():
            r = self.cli(*args)
            GLib.idle_add(self._export_done, r, dest)
        threading.Thread(target=work, daemon=True).start()

    def _export_done(self, r, dest):
        self.set_mode("idle")
        if r.returncode == 0:
            self.notify(T("Exported"), dest)
        else:
            self.error_dialog(T("Could not export"), (r.stderr or r.stdout)[-800:])
        return False

    def on_delete(self):
        if not self.selected:
            return
        name = self.selected.stem
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              text=T("Delete this meeting?"))
        d.format_secondary_text(T("This permanently deletes the notes, transcript and audio of “{name}”. It cannot be undone.", name=name))
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Delete"), Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.CANCEL)
        resp = d.run(); d.destroy()
        if resp == Gtk.ResponseType.OK:
            self._run_action("Deleting…", "delete", name)

    # ---------- settings ----------
    MODELS = [
        ("small", "Small — fast (default)"),
        ("medium", "Medium — more accurate, slower"),
        ("large-v3-turbo", "Large v3 turbo — most accurate, heaviest"),
    ]
    PROVIDERS = [
        ("local", "Local model (private, nothing leaves this computer)"),
        ("claude-code", "Claude Code (installed on this computer)"),
        ("gemini-cli", "Gemini CLI (installed on this computer)"),
    ]

    def _cfg(self, key, default):
        r = self.cli("config", key)
        return (r.stdout.strip() or default) if r.returncode == 0 else default

    def on_settings(self):
        installed = set(self.cli("providers").stdout.split())
        d = Gtk.Dialog(title=T("Settings"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Save"), Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        d.set_default_size(520, 640)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        d.get_content_area().pack_start(scroller, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16); box.set_margin_bottom(12)
        box.set_margin_start(22); box.set_margin_end(22)
        scroller.add(box)

        def heading(text):
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(f"<b>{GLib.markup_escape_text(T(text))}</b>")
            lbl.set_margin_top(10)
            return lbl

        def note(text):
            lbl = Gtk.Label(label=T(text), xalign=0, wrap=True)
            lbl.get_style_context().add_class("dim-label")
            return lbl

        def switch_row(text, active, tip=None):
            row = Gtk.Box(spacing=12)
            lbl = Gtk.Label(label=T(text), xalign=0, wrap=True)
            lbl.set_hexpand(True)
            sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
            row.pack_start(lbl, True, True, 0); row.pack_end(sw, False, False, 0)
            if tip:
                row.set_tooltip_text(T(tip))
            return row, sw

        def combo(options, current, fallback):
            c = Gtk.ComboBoxText()
            for key, label in options:
                c.append(key, T(label))
            c.set_active_id(current if current in {k for k, _ in options} else fallback)
            return c

        # ---- speech recognition
        box.pack_start(heading("Transcription model"), False, False, 0)
        model_box = Gtk.ComboBoxText()
        for key, label in self.MODELS:
            model_box.append(key, T(label))
        current_model = self._cfg("whisper_model", "small")
        if current_model not in {k for k, _ in self.MODELS}:
            model_box.append(current_model, current_model)
        model_box.set_active_id(current_model)
        box.pack_start(model_box, False, False, 0)
        box.pack_start(note("Changing it downloads the model once (up to ~1.5 GB)."), False, False, 0)

        box.pack_start(heading("Processor"), False, False, 0)
        current_device = self._cfg("whisper_device", "auto")
        dev_box = combo([("auto", "Automatic (use the graphics card when there is one)"),
                         ("cpu", "CPU only")], current_device, "auto")
        box.pack_start(dev_box, False, False, 0)

        # ---- voices
        box.pack_start(heading("Voices"), False, False, 0)
        current_diarize = self._cfg("diarize", "on") == "on"
        row, diarize_sw = switch_row("Tell the people on the call apart by their voice", current_diarize)
        box.pack_start(row, False, False, 0)
        box.pack_start(note("Splits the other side of the call into Participant 1, 2... "
                            "Downloads a small model (~46 MB) once."), False, False, 0)
        spk_box = combo([("0", "Number of speakers: automatic")] +
                        [(str(n), f"{n}") for n in range(2, 9)],
                        self._cfg("speakers", "0"), "0")
        box.pack_start(spk_box, False, False, 0)

        # ---- advanced (the options Vibe calls "More options")
        box.pack_start(heading("Advanced"), False, False, 0)
        box.pack_start(Gtk.Label(label=T("Initial prompt"), xalign=0), False, False, 0)
        prompt_entry = Gtk.Entry(text=self._cfg("prompt", ""))
        prompt_entry.set_placeholder_text(T("Names and terms that appear in your meetings"))
        box.pack_start(prompt_entry, False, False, 0)
        box.pack_start(note("Helps the model spell names, products and jargon correctly."), False, False, 0)

        box.pack_start(Gtk.Label(label=T("Accuracy"), xalign=0), False, False, 0)
        beam_box = combo([("1", "Fast (greedy)"), ("5", "Balanced (beam search)"),
                          ("8", "Most accurate (slower)")], self._cfg("beam", "5"), "5")
        box.pack_start(beam_box, False, False, 0)

        row, norm_sw = switch_row("Even out the volume before transcribing",
                                  self._cfg("normalize", "off") == "on")
        box.pack_start(row, False, False, 0)

        threads_row = Gtk.Box(spacing=12)
        threads_row.pack_start(Gtk.Label(label=T("Processor threads (0 = automatic)"), xalign=0), True, True, 0)
        threads = Gtk.SpinButton.new_with_range(0, 32, 1)
        try:
            threads.set_value(int(self._cfg("threads", "0") or 0))
        except ValueError:
            pass
        threads_row.pack_end(threads, False, False, 0)
        box.pack_start(threads_row, False, False, 0)

        # ---- notes writer
        box.pack_start(heading("Who writes the notes"), False, False, 0)
        current_provider = self._cfg("notes_provider", "local")
        radios, group = {}, None
        for key, label in self.PROVIDERS:
            ok = key == "local" or key in installed
            text = T(label) if ok else f"{T(label)} — {T('not installed')}"
            rb = Gtk.RadioButton.new_with_label_from_widget(group, text)
            group = group or rb
            rb.set_sensitive(ok)
            rb.set_active(key == current_provider and ok)
            radios[key] = rb
            box.pack_start(rb, False, False, 0)
        if not any(r.get_active() for r in radios.values()):
            radios["local"].set_active(True)
        warn = note("The transcript of each meeting will be sent to that service using your own account.")
        box.pack_start(warn, False, False, 0)

        def sync_warn(*_):
            warn.set_visible(not radios["local"].get_active())
        for rb in radios.values():
            rb.connect("toggled", sync_warn)
        d.show_all()
        sync_warn()
        resp = d.run()
        new = {
            "whisper_model": model_box.get_active_id() or current_model,
            "whisper_device": dev_box.get_active_id() or current_device,
            "diarize": "on" if diarize_sw.get_active() else "off",
            "speakers": spk_box.get_active_id() or "0",
            "prompt": prompt_entry.get_text().strip(),
            "beam": beam_box.get_active_id() or "5",
            "normalize": "on" if norm_sw.get_active() else "off",
            "threads": str(int(threads.get_value())),
            "notes_provider": next((k for k, rb in radios.items() if rb.get_active()), "local"),
        }
        d.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        for key, val in new.items():
            r = self.cli("config", key, val)
            if r.returncode != 0:
                self.error_dialog(T("Could not save the settings"), r.stderr or r.stdout)
                return
        if new["whisper_model"] != current_model or (new["diarize"] == "on" and not current_diarize):
            self.run_setup()        # downloads the speech / speaker models when they are missing

    # ---------- helpers ----------
    def notify(self, summary, body):
        try:
            n = Notify.Notification.new(summary, body, "meetinginsights")
            n.show()
        except Exception:
            pass

    def error_dialog(self, primary, detail):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.CLOSE, text=primary)
        d.format_secondary_text((detail or "").strip()[:600])
        d.run(); d.destroy()


class MeetingInsightsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="page.saurabh.MeetingInsights")

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_prgname("page.saurabh.MeetingInsights")
        Gtk.Window.set_default_icon_name("meetinginsights")
        Notify.init("MeetingInsights")
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.get_active_window() or MeetingInsightsWindow(self)
        win.show_all()
        win.present()


if __name__ == "__main__":
    import sys
    sys.exit(MeetingInsightsApp().run(sys.argv))

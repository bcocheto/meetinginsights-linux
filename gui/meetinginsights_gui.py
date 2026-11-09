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
        "records, transcribes and writes notes — entirely on your device":
            "grava, transcreve e escreve as atas — tudo no seu dispositivo",
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
    "bg":            "#222226",
    "bg_bar":        "#1b1b1f",
    "surface":       "rgba(255,255,255,0.055)",
    "surface_hover": "rgba(255,255,255,0.13)",
    "field":         "rgba(255,255,255,0.07)",
    "hairline":      "rgba(255,255,255,0.08)",
    "accent":        "#3584e4",
    "accent_soft":   "#62a0ea",
    "text_primary":  "#f2f2f2",
    "text_secondary":"rgba(255,255,255,0.55)",
    "danger":        "#e01b24",
    "warn":          "#f5c211",
}

CSS = ("""
window, .root { background-color: %(bg)s; color: %(text_primary)s; }
headerbar { background: %(bg_bar)s; border-bottom: 1px solid %(hairline)s; box-shadow: none; color: %(text_primary)s; }
headerbar button { border-radius: 999px; background: transparent; border: none; box-shadow: none; color: %(text_secondary)s; }
headerbar button:hover { background: %(surface_hover)s; color: %(text_primary)s; }
.sidebar { background: transparent; }

.timer {
  font-family: monospace; font-size: 30px; font-weight: 300;
  color: %(text_primary)s;
}
.micro {
  font-size: 10px; font-weight: 700; letter-spacing: 1.2px;
  color: %(text_secondary)s;
}
.status-rec  { color: %(danger)s; }
.status-busy { color: %(accent_soft)s; }

entry, searchentry {
  background: %(field)s; color: %(text_primary)s; caret-color: %(accent_soft)s;
  border: 1px solid %(hairline)s; border-radius: 999px; padding: 8px 16px;
  font-size: 14px; box-shadow: none;
}
entry:focus, searchentry:focus { border-color: %(accent_soft)s; background: rgba(255,255,255,0.10); }
searchentry { margin: 10px 10px 6px 10px; padding: 6px 12px; }

combobox button.combo {
  background: %(field)s; color: %(text_primary)s; border: 1px solid %(hairline)s;
  border-radius: 999px; padding: 6px 14px; box-shadow: none;
}
combobox button.combo:hover { background: %(surface_hover)s; }

button.loud {
  background: %(accent)s; color: #ffffff; border: none; box-shadow: none;
  border-radius: 999px; padding: 9px 24px; font-weight: 700;
}
button.loud:hover { background: %(accent_soft)s; }
button.quiet {
  background: %(surface)s; color: %(text_primary)s;
  border: 1px solid %(hairline)s; border-radius: 999px; box-shadow: none;
  padding: 9px 24px; font-weight: 600;
}
button.quiet:hover { background: %(surface_hover)s; }
button.loud:disabled, button.quiet:disabled {
  background: %(surface)s; color: %(text_secondary)s; border: 1px solid %(hairline)s;
}

/* meeting list: one rounded card per meeting */
list, list row { background: transparent; }
list row {
  margin: 3px 10px; padding: 10px 12px; border-radius: 12px;
  background: %(surface)s; border: 1px solid rgba(255,255,255,0.05);
}
list row:hover { background: %(surface_hover)s; }
list row:selected { background: alpha(%(accent_soft)s, 0.22); border-color: %(accent_soft)s; }
.row-title { color: %(text_primary)s; font-weight: 600; }
.row-meta  { color: %(text_secondary)s; font-size: 11px; }
.badge {
  min-width: 32px; min-height: 32px; border-radius: 10px;
  background: alpha(%(accent_soft)s, 0.25); color: #ffffff;
}
.empty { color: %(text_secondary)s; font-size: 13px; }

/* action bar: chips, as in Gavetta's filters */
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
body { background:#222226; color:#e6e6e8; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
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

        hb = Gtk.HeaderBar(show_close_button=True, title="MeetingInsights")
        hb.set_subtitle(T("records, transcribes and writes notes — entirely on your device"))
        self.set_titlebar(hb)
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_btn.set_tooltip_text(T("Reload meetings"))
        self.refresh_btn.connect("clicked", lambda *_: self.load_meetings())
        hb.pack_end(self.refresh_btn)
        self.settings_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        self.settings_btn.set_tooltip_text(T("Settings"))
        self.settings_btn.connect("clicked", lambda *_: self.on_settings())
        hb.pack_end(self.settings_btn)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.get_style_context().add_class("root")
        self.add(root)
        root.pack_start(self._build_controls(), False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(340)
        root.pack_start(paned, True, True, 0)

        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.get_style_context().add_class("sidebar")
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-selected", self.on_select)
        sw.add(self.listbox)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("sidebar")
        self.search = Gtk.SearchEntry(placeholder_text=T("Search meetings…"))
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        side.pack_start(self.search, False, False, 0)
        side.pack_start(sw, True, True, 0)
        self.listbox.set_filter_func(self._filter_row)
        paned.pack1(side, False, False)

        self.webview = WebKit2.WebView()
        self.webview.set_background_color(Gdk.RGBA(0.133, 0.133, 0.149, 1))
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.pack_start(self._build_actions(), False, False, 0)
        right.pack_start(self.webview, True, True, 0)
        paned.pack2(right, True, False)
        self.selected = None

        self.load_meetings()
        first = self.listbox.get_row_at_index(0)
        if first is not None and hasattr(first, "path"):
            self.listbox.select_row(first)
        self.poll_state()
        GLib.idle_add(lambda: (self.set_focus(None), False)[1])
        GLib.timeout_add(400, self._first_run_check)
        GLib.timeout_add_seconds(1, self.tick)

    def _build_controls(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(14); box.set_margin_bottom(14)
        box.set_margin_start(16); box.set_margin_end(16)

        self.entry = Gtk.Entry(placeholder_text=T("Meeting title  (e.g. SSO standup)"))
        self.entry.set_hexpand(True)
        self.entry.connect("activate", lambda *_: self.on_record())
        box.pack_start(self.entry, True, True, 0)

        self.lang_box = Gtk.ComboBoxText()
        self.lang_box.set_tooltip_text(T("Spoken language of the meeting"))
        for key, label in LANGUAGES:
            self.lang_box.append(key, label)
        self.lang_box.set_active_id(self._saved_language())
        self.lang_box.connect("changed", self.on_language_changed)
        box.pack_start(self.lang_box, False, False, 0)

        self.timer_lbl = Gtk.Label(label="00:00")
        self.timer_lbl.get_style_context().add_class("timer")
        box.pack_start(self.timer_lbl, False, False, 0)

        self.status_lbl = Gtk.Label(label=T("Idle"))
        self.status_lbl.get_style_context().add_class("micro")
        box.pack_start(self.status_lbl, False, False, 0)

        self.rec_btn = Gtk.Button(label=T("Record"))
        self.rec_btn.get_style_context().add_class("loud")
        self.rec_btn.connect("clicked", lambda *_: self.on_record())
        box.pack_start(self.rec_btn, False, False, 0)
        return box

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
            body = "".join(
                f"<p><span class='t'>{html.escape(t)}</span> "
                f"<span class='s'>{html.escape(sp)}</span> {html.escape(rest)}</p>"
                for t, sp, rest in (self._split_turn(l) for l in text.splitlines() if l.strip()))
            note = "<p class='hint'>Transcribing as the meeting runs — the rest is written when you press Stop.</p>"
        else:
            body = ""
            note = ("<p class='hint'>Listening. The first lines appear after about "
                    "a minute of speech.</p>")
        self.webview.load_html(
            f"<style>{NOTE_CSS}"
            ".t{color:#7C8B93;font-family:monospace;font-size:12px}"
            ".s{color:#66B29D;font-weight:600}"
            ".hint{color:#7C8B93;font-style:italic}"
            "p{margin:6px 0}</style>"
            f"<h2>Live transcript</h2>{note}{body}"
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
        btn = self.rec_btn.get_style_context()
        for c in ("loud", "quiet"):
            btn.remove_class(c)
        self.mode = mode
        self.lang_box.set_sensitive(mode == "idle")
        if hasattr(self, "action_btns"):
            self._refresh_actions()
        if mode == "recording":
            self.status_lbl.set_text(T("● RECORDING")); ctx.add_class("status-rec")
            self.rec_btn.set_label(T("Stop")); btn.add_class("quiet")
            self.rec_btn.set_sensitive(True); self.entry.set_sensitive(False)
        elif mode == "busy":
            self.status_lbl.set_text(note or T("Working…")); ctx.add_class("status-busy")
            self.rec_btn.set_label(T("Working…")); btn.add_class("quiet")
            self.rec_btn.set_sensitive(False); self.entry.set_sensitive(False)
        else:
            self.status_lbl.set_text(T("IDLE"))
            self.rec_btn.set_label(T("Record")); btn.add_class("loud")
            self.rec_btn.set_sensitive(True); self.entry.set_sensitive(True)
            self.timer_lbl.set_text("00:00"); self.started_at = None

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
            lbl = Gtk.Label(label=T("No meetings yet.\nEnter a title and press Record."))
            lbl.get_style_context().add_class("empty")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_margin_top(40)
            row.add(lbl); self.listbox.add(row); self.listbox.show_all()
            self.webview.load_html(f"<style>{NOTE_CSS}</style>"
                                   "<p style='color:#6b7080'>" + T("Select a meeting to read its notes.") + "</p>", None)
            return
        for f in files:
            self.listbox.add(self._meeting_row(f))
        self.listbox.show_all()

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
            return
        self.selected = row.path
        self._refresh_actions()
        try:
            md = row.path.read_text()
        except OSError as e:
            md = f"# {T('Could not read notes')}\n\n{e}"
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
                b.set_halign(Gtk.Align.END); b.set_hexpand(True)
            b.connect("clicked", lambda _b, h=handler: h())
            b.set_sensitive(False)
            bar.pack_start(b, False, False, 0)
            self.action_btns.append(b)
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
        box = d.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(16); box.set_margin_bottom(8)
        box.set_margin_start(20); box.set_margin_end(20)

        def heading(text):
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(f"<b>{GLib.markup_escape_text(T(text))}</b>")
            return lbl

        box.pack_start(heading("Transcription model"), False, False, 0)
        model_box = Gtk.ComboBoxText()
        for key, label in self.MODELS:
            model_box.append(key, T(label))
        current_model = self._cfg("whisper_model", "small")
        if current_model not in {k for k, _ in self.MODELS}:
            model_box.append(current_model, current_model)
        model_box.set_active_id(current_model)
        box.pack_start(model_box, False, False, 0)
        hint = Gtk.Label(label=T("Changing it downloads the model once (up to ~1.5 GB)."), xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        box.pack_start(heading("Who writes the notes"), False, False, 6)
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
        warn = Gtk.Label(label=T("The transcript of each meeting will be sent to that service using your own account."),
                         xalign=0, wrap=True)
        warn.get_style_context().add_class("dim-label")
        box.pack_start(warn, False, False, 0)

        def sync_warn(*_):
            warn.set_visible(not radios["local"].get_active())
        for rb in radios.values():
            rb.connect("toggled", sync_warn)
        d.show_all()
        sync_warn()
        resp = d.run()
        new_model = model_box.get_active_id() or current_model
        new_provider = next((k for k, rb in radios.items() if rb.get_active()), "local")
        d.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        for key, val in (("whisper_model", new_model), ("notes_provider", new_provider)):
            r = self.cli("config", key, val)
            if r.returncode != 0:
                self.error_dialog(T("Could not save the settings"), r.stderr or r.stdout)
                return
        if new_model != current_model:
            self.run_setup()        # downloads the new speech model if it is not cached yet

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

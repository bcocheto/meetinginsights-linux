#!/usr/bin/env python3
"""Minuta — GTK desktop app for on-device meeting recording, transcription and notes.

The UI is a thin layer over the `minuta` CLI: it shells out for start/stop and
reads the resulting markdown from the notes directory. Everything — recording,
transcription and note writing — happens on this machine; nothing is uploaded.
"""
import html
import json
import os
import queue
import re
import shutil
import subprocess
import sys
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
        "Set up Minuta": "Configurar o Minuta",
        "<b>One-time setup</b>": "<b>Configuração inicial</b>",
        "Minuta needs a speech model and a language model so it can "
        "transcribe and summarise without sending anything to a server.\n\n"
        "This downloads about 1.5 GB once. Everything afterwards runs offline.":
            "O Minuta precisa de um modelo de fala e de um modelo de linguagem para "
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
        "Client (optional)": "Cliente (opcional)",
        "What matters in this meeting? (optional)": "O que importa nesta reunião? (opcional)",
        "Glossary": "Glossário",
        "Send action items to Trello…": "Enviar itens de ação ao Trello…", "Trello: choose the list…": "Trello: escolher a lista…",
        "Connect to Trello": "Conectar ao Trello", "Connect": "Conectar", "Open the Trello page": "Abrir a página do Trello",
        "API key": "Chave de API", "Token": "Token",
        "Create an API key and a token on Trello's page for developers, and paste them here. "
        "They are kept in a file only you can read. Nothing is sent to Trello until you "
        "send action items.":
            "Crie uma chave de API e um token na página de desenvolvedores do Trello e cole aqui. Eles ficam "
            "num arquivo que só você lê. Nada é enviado ao Trello até você enviar itens de ação.",
        "Could not connect to Trello": "Não foi possível conectar ao Trello", "Trello": "Trello",
        "No boards found on this account.": "Nenhum quadro encontrado nesta conta.",
        "Where should the cards go?": "Para onde vão os cartões?", "Board": "Quadro", "List": "Lista",
        "This meeting has no action items.": "Esta reunião não tem itens de ação.",
        "Send action items to Trello": "Enviar itens de ação ao Trello", "Create cards": "Criar cartões",
        "Cards will be created in “{list}”. The text of the checked items and the "
        "meeting title are sent to Trello.":
            "Os cartões serão criados em “{list}”. O texto dos itens marcados e o título da reunião são enviados ao Trello.",
        "already sent": "já enviado", "{n} cards created.": "{n} cartões criados.",
        "Some cards were not created": "Alguns cartões não foram criados", "Trello: {title}": "Trello: {title}",
        "Obsidian note": "Nota no Obsidian", "Choose the Obsidian vault…": "Escolher o vault do Obsidian…",
        "Choose the Obsidian vault": "Escolher o vault do Obsidian", "Select": "Selecionar",
        "Could not export to Obsidian": "Não foi possível exportar para o Obsidian",
        "Saved in Obsidian": "Salvo no Obsidian",
        "In your Obsidian vault (optional)": "No seu vault do Obsidian (opcional)",
        "Folder for this client's meetings, e.g. Clients/Acme/Meetings": "Pasta das reuniões deste cliente, ex.: Clientes/Acme/Reuniões",
        "Hub note to link back to, e.g. Clients/Acme/_HUB": "Nota-hub para linkar, ex.: Clientes/Acme/_HUB",
        "Index note that lists the meetings (a line is added)": "Nota de índice que lista as reuniões (uma linha é adicionada)",
        "Show only one client": "Mostrar só um cliente", "All clients": "Todos os clientes",
        "transcript": "transcrição",
        "Finishing the recording…": "Finalizando a gravação…",
        "Processing: {name}": "Processando: {name}", "Waiting to process": "Aguardando para processar",
        "{n} waiting": "{n} na fila", "Unfinished recording": "Gravação não concluída",
        "Could not stop the recording": "Não foi possível parar a gravação",
        "Microphone": "Microfone", "Call audio": "Áudio da chamada",
        "The microphone is not picking up anything. Check that it is plugged in, "
        "not muted, and selected in Sound settings.":
            "O microfone não está captando nada. Veja se está conectado, sem mudo e escolhido nas "
            "configurações de Som.",
        "No sound from the microphone for a while.": "Sem som no microfone há um tempo.",
        "The call audio is not being captured. Check the output device in Sound "
        "settings. Headphones are fine, but the call must play on this computer.":
            "O áudio da chamada não está sendo capturado. Veja o dispositivo de saída nas "
            "configurações de Som. Fone de ouvido serve, mas a chamada precisa tocar neste computador.",
        "No call audio for a while.": "Sem áudio da chamada há um tempo.",
        "Local model: small (0.5 GB, fast)": "Modelo local: pequeno (0,5 GB, rápido)",
        "Local model: medium (2 GB, better summaries)": "Modelo local: médio (2 GB, resumos melhores)",
        "Used when the notes are written on this computer. The medium model "
        "downloads ~2 GB once and needs about 3 GB of free memory.":
            "Usado quando a ata é escrita neste computador. O modelo médio baixa ~2 GB uma vez "
            "e precisa de cerca de 3 GB de memória livre.",
        "A recording was left unfinished": "Há uma gravação não concluída",
        "The audio was saved. Process it now to get the transcript and notes?":
            "O áudio foi salvo. Processar agora para obter a transcrição e a ata?",
        "Later": "Depois", "Process now": "Processar agora",
        "Glossary for {client}": "Glossário de {client}",
        "Names and terms that this client uses. They help the transcription and the notes.":
            "Nomes e termos que esse cliente usa. Ajudam a transcrição e a ata.",
        "Type the client's name first.": "Digite antes o nome do cliente.",
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
        "Welcome to Minuta": "Bem-vindo ao Minuta",
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
        "Speakers": "Falantes",
        "Keyboard shortcut": "Atalho de teclado",
        "Starts and stops a recording from anywhere, for example <Super><Alt>r. Leave it empty for none. Needs GNOME.": "Inicia e para uma gravação de qualquer lugar, por exemplo <Super><Alt>r. Deixe vazio para não usar. Precisa do GNOME.",
        "Could not set the shortcut": "Não foi possível definir o atalho",
        "Rename speakers": "Renomear falantes",
        "Type the real name next to each speaker; leave it empty to keep it. Two speakers with the same name are merged.": "Digite o nome real ao lado de cada falante; deixe vazio para manter. Dois falantes com o mesmo nome são unidos.",
        "lines": "falas",
        "Could not rename the speakers": "Não foi possível renomear os falantes",
        "Speakers renamed": "Falantes renomeados",
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
NOTES_DIR = Path(os.environ.get("MINUTA_OUT", HOME / "MeetingNotes"))
for _lib in (Path(__file__).resolve().parent.parent / "lib", Path("/usr/share/minuta/lib")):
    if (_lib / "levels.py").exists():
        sys.path.insert(0, str(_lib)); break
import levels  # noqa: E402
import search as msearch  # noqa: E402

DATA_DIR = Path(os.environ.get("MINUTA_HOME", HOME / ".local/share/minuta"))
LANG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "minuta" / "language"
LANGUAGES = [  # (setting stored in the config file, label)
    ("system", T("Language: system default")),
    ("auto", T("Language: auto-detect")),
    ("pt", "Português"), ("en", "English"), ("es", "Español"),
    ("fr", "Français"), ("de", "Deutsch"), ("it", "Italiano"),
]
REC_DIR = Path(os.environ.get("MINUTA_HOME", HOME / ".local/share/minuta")) / "rec"
CLI = os.environ.get("MINUTA_CLI") or shutil.which("minuta") or str(
    Path(__file__).resolve().parent.parent / "bin" / "minuta")

try:   # the first call also carries the data over from the app's former name (MeetingInsights)
    subprocess.run([CLI, "status"], capture_output=True, timeout=60)
except (OSError, subprocess.SubprocessError):
    pass

# ---------------------------------------------------------------- theme
# Same visual language as Gavetta, Clima and Cadência: neutral surface, GNOME blue
# accent, rounded cards (12px), pill inputs and chips, hairline borders. Dark or light
# follows the system (org.gnome.desktop.interface color-scheme); MINUTA_THEME overrides.
THEME_DARK = {
    "bg":            "#222226",
    "bg_bar":        "#1c1c20",
    "surface":       "rgba(255,255,255,0.055)",
    "surface_hover": "rgba(255,255,255,0.10)",
    "field":         "rgba(255,255,255,0.07)",
    "hairline":      "rgba(255,255,255,0.10)",
    "accent":        "#3584e4",
    "accent_soft":   "#62a0ea",
    "text_primary":  "#f2f2f2",
    "text_secondary":"rgba(255,255,255,0.55)",
    "danger":        "#e01b24",
    "warn":          "#f5c211",
    "ok":            "#57e389",
    "cloud":         "#ffa348",
    "ink":           "255,255,255",
    "strong":        "#ffffff",
}
THEME_LIGHT = {
    "bg":            "#fafafb",
    "bg_bar":        "#f0f0f3",
    "surface":       "rgba(0,0,0,0.045)",
    "surface_hover": "rgba(0,0,0,0.08)",
    "field":         "rgba(0,0,0,0.05)",
    "hairline":      "rgba(0,0,0,0.12)",
    "accent":        "#3584e4",
    "accent_soft":   "#1c71d8",
    "text_primary":  "#241f31",
    "text_secondary":"rgba(0,0,0,0.58)",
    "danger":        "#c01c28",
    "warn":          "#b8860b",
    "ok":            "#1a7f4b",
    "cloud":         "#b85c00",
    "ink":           "0,0,0",
    "strong":        "#000000",
}


def system_is_dark() -> bool:
    forced = os.environ.get("MINUTA_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=3).stdout
        return "light" not in out
    except (OSError, subprocess.SubprocessError):
        return True


IS_DARK = system_is_dark()
THEME = THEME_DARK if IS_DARK else THEME_LIGHT


def themed(css: str) -> str:
    """Fill the %(token)s placeholders; overlays written as white become black on light."""
    css = css.replace("rgba(255,255,255,", "rgba(%(ink)s,").replace("rgba(255, 255, 255, ", "rgba(%(ink)s, ")
    return re.sub(r"%\((\w+)\)s", lambda m: THEME[m.group(1)], css)


_CSS_SRC = """
window, .root { background-color: %(bg)s; color: %(text_primary)s; }
headerbar { background: %(bg_bar)s; border-bottom: 1px solid %(hairline)s; box-shadow: none; color: %(text_primary)s; min-height: 38px; }
headerbar button { border-radius: 999px; background: transparent; border: none; box-shadow: none; color: %(text_secondary)s; }
headerbar button:hover { background: %(surface_hover)s; color: %(text_primary)s; }

/* sidebar: flat, like Vibe */
.sidebar { background: %(bg)s; padding: 14px 8px 4px 8px; }
.sidebar-title { font-size: 16px; font-weight: 700; padding: 2px 10px 10px 10px; }
.section-label { font-size: 11px; font-weight: 700; letter-spacing: 0.6px; color: %(text_secondary)s; padding: 16px 10px 6px 10px; }
button.nav {
  background: transparent; border: none; box-shadow: none; color: %(text_primary)s;
  border-radius: 12px; padding: 8px 10px; font-weight: 500;
}
button.nav:hover { background: %(surface_hover)s; }
separator { background: %(hairline)s; min-width: 1px; min-height: 1px; margin: 0; }

.timer { font-family: monospace; font-size: 26px; font-weight: 300; color: %(text_primary)s; }
.micro { font-size: 10px; font-weight: 700; letter-spacing: 1.2px; color: %(text_secondary)s; }
.status-rec  { color: %(danger)s; }
.status-busy { color: %(accent_soft)s; }
.dim-label { color: %(text_secondary)s; font-size: 12px; }
.dim-icon { color: %(text_secondary)s; }
.drop-title { font-size: 16px; font-weight: 600; color: %(text_primary)s; }

entry, searchentry {
  background: %(field)s; color: %(text_primary)s; caret-color: %(accent_soft)s;
  border: 1px solid %(hairline)s; border-radius: 999px; padding: 9px 18px;
  font-size: 14px; box-shadow: none;
}
entry:focus, searchentry:focus { border-color: %(accent_soft)s; background: rgba(255,255,255,0.09); }
entry image, searchentry image { color: %(text_secondary)s; }
entry placeholder, searchentry placeholder { color: %(text_secondary)s; }
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
list row { margin: 1px 4px; padding: 8px 10px; border-radius: 12px; border: 1px solid transparent; }
list row, list row image { color: %(text_primary)s; }
list row:hover { background: %(surface_hover)s; }
list row:selected { background: alpha(%(accent)s, 0.22); border-color: alpha(%(accent_soft)s, 0.60); }
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
  border: 1.5px dashed %(hairline)s; border-radius: 18px; padding: 34px 28px;
}
eventbox:hover .dropzone { border-color: %(accent_soft)s; }

.tag-local, .tag-cloud { font-size: 11px; font-weight: 700; padding: 3px 12px; border-radius: 999px; }
.tag-local { color: %(ok)s; background: alpha(%(ok)s, 0.14); }
.tag-cloud { color: %(cloud)s; background: alpha(%(cloud)s, 0.16); }

/* action bar: chips */
button.chip {
  padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 700;
  background: %(surface)s; color: %(text_secondary)s;
  border: none; box-shadow: none;
}
button.chip:hover { background: rgba(255,255,255,0.15); color: %(strong)s; }
button.chip.danger:hover { background: alpha(%(danger)s, 0.60); color: #ffffff; }
button.chip:disabled { color: alpha(%(text_secondary)s, 0.5); }

dialog, messagedialog { background: %(bg)s; color: %(text_primary)s; }
dialog .dialog-action-area button, messagedialog .dialog-action-area button {
  background: %(surface)s; color: %(text_primary)s; border: 1px solid %(hairline)s;
  border-radius: 999px; box-shadow: none; padding: 6px 20px; font-weight: 600;
}
dialog .dialog-action-area button:hover, messagedialog .dialog-action-area button:hover { background: %(surface_hover)s; }
dialog .dialog-action-area button.suggested-action, messagedialog .dialog-action-area button.suggested-action {
  background: %(accent)s; color: #ffffff; border: none;
}
dialog .dialog-action-area button.suggested-action:hover, messagedialog .dialog-action-area button.suggested-action:hover { background: %(accent_soft)s; }
"""
CSS = themed(_CSS_SRC).encode()

_NOTE_SRC = """
:root { color-scheme: %(scheme)s; }
body { background:%(bg)s; color:%(text_primary)s; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       font-size: 14px; line-height: 1.65; padding: 24px 28px; margin:0; }
h1 { font-size: 21px; color:%(strong)s; margin:0 0 4px; }
h2 { font-size: 13px; letter-spacing: .6px; text-transform: uppercase; color: rgba(255,255,255,.55);
     margin: 26px 0 10px; font-weight: 700; }
h3 { font-size: 13.5px; color:%(text_primary)s; margin: 16px 0 4px; }
table { border-collapse: separate; border-spacing: 0; width:100%; margin:10px 0; font-size:13px;
        border:1px solid %(hairline)s; border-radius:12px; overflow:hidden; }
th { text-align:left; background:rgba(255,255,255,.07); color:rgba(255,255,255,.7); padding:8px 12px; }
td { padding:8px 12px; border-top:1px solid rgba(255,255,255,.06); vertical-align: top; }
code { background:rgba(255,255,255,.08); padding:1px 6px; border-radius:6px; font-size:12.5px; }
blockquote { border-left:3px solid %(accent_soft)s; margin:12px 0; padding:8px 14px; color:rgba(255,255,255,.65);
             background:rgba(255,255,255,.04); border-radius:0 10px 10px 0; }
strong { color:%(strong)s; }
ul,ol { padding-left: 22px; }
li { margin: 4px 0; }
li::marker { color:%(accent_soft)s; }
a { color:%(accent_soft)s; }
pre { background:rgba(255,255,255,.05); border-radius:12px; padding:12px 14px; }
.turn { margin: 0 0 16px; }
.who { font-weight: 700; font-size: 13px; }
.ts { font-weight: 400; font-size: 11px; margin-left: 8px; color: rgba(255,255,255,.38);
      font-variant-numeric: tabular-nums; }
.say { margin: 3px 0 0; padding: 1px 0 1px 12px; border-left: 2px solid var(--c); color: %(text_primary)s; }
em { color: rgba(255,255,255,.6); }
"""
NOTE_CSS = themed(_NOTE_SRC.replace("%(scheme)s", "dark" if IS_DARK else "light"))

SPEAKER_COLORS = (["#62a0ea", "#57e389", "#f5c211", "#dc8add", "#ffa348", "#78aeed"] if IS_DARK else
                  ["#1c71d8", "#1a7f4b", "#9a6a00", "#9141ac", "#b85c00", "#1a5fb4"])


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

    The work is done by `minuta setup --porcelain`, which emits
    STEP/PCT/ERR/DONE lines; this dialog only renders them. Keeping the logic in
    the CLI means the terminal and the desktop app cannot drift apart.
    """

    def __init__(self, parent, cli):
        super().__init__(title=T("Set up Minuta"), transient_for=parent, modal=True)
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
            "Minuta needs a speech model and a language model so it can "
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


class MinutaWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Minuta")
        self.set_default_size(1120, 720)
        self.busy = False
        self.started_at = None
        self.mode = "idle"
        self.selected = None

        hb = Gtk.HeaderBar(show_close_button=True, title="Minuta")
        self.set_titlebar(hb)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.get_style_context().add_class("root")
        self.add(root)

        # ---- sidebar: title, new meeting, recents, settings
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("sidebar")
        side.set_size_request(270, -1)
        title = Gtk.Label(label="Minuta", xalign=0)
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
        self.search.connect("search-changed", lambda *_: self._apply_search())
        side.pack_start(self.search, False, False, 0)
        self.client_filter = Gtk.ComboBoxText()
        self.client_filter.set_tooltip_text(T("Show only one client"))
        self.client_filter.connect("changed", lambda *_: self._apply_search())
        self.client_filter.set_no_show_all(True)
        side.pack_start(self.client_filter, False, False, 0)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-selected", self.on_select)
        self.listbox.set_filter_func(self._filter_row)
        self.listbox.set_sort_func(self._sort_rows)
        self._hits, self._meetings, self._query, self._client = {}, [], "", ""
        sw.add(self.listbox)
        side.pack_start(sw, True, True, 0)
        self.queue_box = Gtk.Box(spacing=8)
        self.queue_box.set_margin_start(14); self.queue_box.set_margin_end(14)
        self.queue_box.set_margin_top(8); self.queue_box.set_margin_bottom(4)
        self.queue_spin = Gtk.Spinner()
        self.queue_lbl = Gtk.Label(label="", xalign=0, wrap=True)
        self.queue_lbl.get_style_context().add_class("dim-label")
        self.queue_box.pack_start(self.queue_spin, False, False, 0)
        self.queue_box.pack_start(self.queue_lbl, True, True, 0)
        self.queue_box.show_all(); self.queue_box.set_no_show_all(True); self.queue_box.hide()
        side.pack_start(self.queue_box, False, False, 0)
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
        GLib.timeout_add(1500, self._recover_check)
        GLib.timeout_add_seconds(1, self.tick)
        GLib.timeout_add(200, self._levels_tick)

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

        # per-meeting context, shared by recording and importing
        ctxbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        crow = Gtk.Box(spacing=8)
        self.client_box = Gtk.ComboBoxText.new_with_entry()
        self.client_box.get_child().set_placeholder_text(T("Client (optional)"))
        crow.pack_start(self.client_box, True, True, 0)
        self.gloss_btn = Gtk.Button(label=T("Glossary"))
        self.gloss_btn.get_style_context().add_class("nav")
        self.gloss_btn.connect("clicked", lambda *_: self.on_glossary())
        crow.pack_start(self.gloss_btn, False, False, 0)
        ctxbox.pack_start(crow, False, False, 0)
        self.focus_entry = Gtk.Entry(placeholder_text=T("What matters in this meeting? (optional)"))
        self.focus_entry.set_max_length(500)
        ctxbox.pack_start(self.focus_entry, False, False, 0)
        col.pack_start(ctxbox, False, False, 0)
        self.refresh_clients()

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

    def refresh_clients(self):
        self.client_box.remove_all()
        r = self.cli("client", "list")
        for name in r.stdout.splitlines():
            if name.strip():
                self.client_box.append_text(name.strip())

    def _meta_args(self):
        client = self.client_box.get_child().get_text().strip()
        focus = self.focus_entry.get_text().strip()
        return (["--client", client] if client else []) + (["--focus", focus] if focus else [])

    def on_glossary(self):
        client = self.client_box.get_child().get_text().strip()
        if not client:
            self.error_dialog(T("Glossary"), T("Type the client's name first."))
            return
        d = Gtk.Dialog(title=T("Glossary for {client}", client=client), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Save"), Gtk.ResponseType.OK)
        area = d.get_content_area(); area.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(area.props, m, 14)
        info = Gtk.Label(label=T("Names and terms that this client uses. They help the transcription and the notes."))
        info.set_line_wrap(True); info.set_xalign(0)
        area.pack_start(info, False, False, 0)
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD)
        tv.set_size_request(420, 120)
        tv.get_buffer().set_text(self.cli("client", "show", client).stdout.strip())
        area.pack_start(tv, True, True, 0)
        cfg = dict(ln.split("=", 1) for ln in self.cli("client", "config", client).stdout.splitlines() if "=" in ln)
        area.pack_start(Gtk.Label(label=T("In your Obsidian vault (optional)"), xalign=0), False, False, 6)
        fields = {}
        for key, hint in (("folder", "Folder for this client's meetings, e.g. Clients/Acme/Meetings"),
                          ("hub", "Hub note to link back to, e.g. Clients/Acme/_HUB"),
                          ("index", "Index note that lists the meetings (a line is added)")):
            e = Gtk.Entry(text=cfg.get(key, "")); e.set_placeholder_text(T(hint))
            fields[key] = e
            area.pack_start(e, False, False, 0)
        d.show_all()
        resp = d.run()
        b = tv.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()
        obs_vals = {k: e.get_text().strip() for k, e in fields.items()}
        d.destroy()
        if resp == Gtk.ResponseType.OK:
            if text:
                self.cli("client", "set", client, text)
            elif not any(v for v in obs_vals.values()):
                self.cli("client", "rm", client)
            for key, val in obs_vals.items():
                self.cli("client", "config", client, key, val)
            self.refresh_clients()
            self.client_box.get_child().set_text(client)

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
        self.submit_job(Path(path).stem, ("import", path, *self._meta_args()), self._stop_done)

    def on_new_meeting(self):
        if self.mode != "idle":
            return
        self.listbox.unselect_all()
        self.selected = None
        self._update_stage()

    def _meter(self, text):
        box = Gtk.Box(spacing=6)
        lbl = Gtk.Label(label=T(text)); lbl.get_style_context().add_class("micro")
        bar = Gtk.LevelBar(); bar.set_min_value(0); bar.set_max_value(1)
        bar.set_size_request(70, 8); bar.set_valign(Gtk.Align.CENTER)
        box.pack_start(lbl, False, False, 0); box.pack_start(bar, False, False, 0)
        return box, bar

    def _build_recbar(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.pack_start(self._build_recbar_row(), False, False, 0)
        self.audio_warn = Gtk.Label(label="", xalign=0, wrap=True)
        self.audio_warn.get_style_context().add_class("status-rec")
        self.audio_warn.set_margin_start(18); self.audio_warn.set_margin_end(18)
        self.audio_warn.set_margin_bottom(8)
        self.audio_warn.set_no_show_all(True)
        wrap.pack_start(self.audio_warn, False, False, 0)
        return wrap

    def _build_recbar_row(self):
        bar = Gtk.Box(spacing=14)
        bar.set_margin_top(10); bar.set_margin_bottom(10)
        bar.set_margin_start(18); bar.set_margin_end(18)
        self.status_lbl = Gtk.Label(label=T("Idle"))
        self.status_lbl.get_style_context().add_class("micro")
        bar.pack_start(self.status_lbl, False, False, 0)
        self.timer_lbl = Gtk.Label(label="00:00")
        self.timer_lbl.get_style_context().add_class("timer")
        bar.pack_start(self.timer_lbl, False, False, 0)
        mic_box, self.mic_bar = self._meter("Microphone")
        sys_box, self.sys_bar = self._meter("Call audio")
        self.meters = Gtk.Box(spacing=14)
        self.meters.pack_start(mic_box, False, False, 0)
        self.meters.pack_start(sys_box, False, False, 0)
        self.meters.show_all(); self.meters.set_no_show_all(True); self.meters.hide()
        bar.pack_start(self.meters, False, False, 0)
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

    def _levels_tick(self):
        """Update the input meters and warn when a channel has gone quiet (5x a second)."""
        if self.mode != "recording":
            self.meters.hide(); self.audio_warn.hide(); self._watch = None
            return True
        base = self.current_base()
        if not base:
            return True
        self.meters.show()
        now = time.time()
        if getattr(self, "_watch", None) is None or self._watch_base != str(base):
            self._watch_base = str(base)
            self._watch = {"mic": levels.Watch(now), "sys": levels.Watch(now)}
        db = {"mic": levels.tail_db(f"{base}.mic.wav"), "sys": levels.tail_db(f"{base}.sys.wav")}
        for k, w in self._watch.items():
            w.update(db[k], now)
        self.mic_bar.set_value(levels.as_fraction(db["mic"]))
        self.sys_bar.set_value(levels.as_fraction(db["sys"]))
        msgs = []
        st = self._watch["mic"].state(now)
        if st == "dead":
            msgs.append(T("The microphone is not picking up anything. Check that it is plugged in, "
                          "not muted, and selected in Sound settings."))
        elif st == "quiet":
            msgs.append(T("No sound from the microphone for a while."))
        st = self._watch["sys"].state(now)
        if st == "dead":
            msgs.append(T("The call audio is not being captured. Check the output device in Sound "
                          "settings. Headphones are fine, but the call must play on this computer."))
        elif st == "quiet":
            msgs.append(T("No call audio for a while."))
        if msgs:
            self.audio_warn.set_text("⚠  " + "  ".join(msgs)); self.audio_warn.show()
        else:
            self.audio_warn.hide()
        return True

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
            f"<style>{NOTE_CSS}.hint{{color:{THEME['text_secondary']};font-style:italic}}</style>"
            f"<h2>{html.escape(T('Live transcript'))}</h2>{note}{body}"
            "<script>window.scrollTo(0, document.body.scrollHeight);</script>", None)

    @staticmethod
    def _split_turn(line):
        m = re.match(r"\[(\d{2}:\d{2})\]\s+([^:]+):\s*(.*)", line.strip())
        return m.groups() if m else ("", "", line.strip())

    # ---------- first run ----------
    def is_ready(self):
        """`minuta ready` exits non-zero until setup has been run."""
        try:
            return self.cli("ready").returncode == 0
        except Exception:
            return False

    def _recover_check(self):
        """Offer to finish a recording that was cut short (crash, power loss) or left without notes."""
        if self.mode != "idle" or not self.is_ready():
            return False
        items = self.cli("recover", "--list").stdout.split()
        if not items:
            return False
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              text=T("A recording was left unfinished"))
        d.format_secondary_text(T("The audio was saved. Process it now to get the transcript and notes?"))
        d.add_button(T("Later"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Process now"), Gtk.ResponseType.OK)
        resp = d.run(); d.destroy()
        if resp == Gtk.ResponseType.OK:
            self.submit_job(T("Unfinished recording"), ("recover",), self._stop_done)
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
    def cli(self, *args, timeout=900, input=None):
        return subprocess.run([CLI, *args], capture_output=True, text=True, timeout=timeout, input=input)

    # ---------- background jobs: transcribing and writing notes never block the window ----------
    def submit_job(self, label, args, on_done):
        """Queue a CLI command; jobs run one at a time, in order, while the app stays usable."""
        if not hasattr(self, "_jobq"):
            self._jobq, self._job_waiting, self._job_cur = queue.Queue(), [], None
            threading.Thread(target=self._job_worker, daemon=True).start()
        self._job_waiting.append(label)
        self._jobq.put((label, args, on_done))
        self._refresh_queue()

    def _job_worker(self):
        while True:
            label, args, on_done = self._jobq.get()
            try:
                self._job_waiting.remove(label)
            except ValueError:
                pass
            self._job_cur = label
            GLib.idle_add(self._refresh_queue)
            try:
                r = self.cli(*args, timeout=None)
            except Exception as e:  # noqa: BLE001 - report it instead of killing the worker
                r = subprocess.CompletedProcess(args, 1, "", str(e))
            self._job_cur = None
            GLib.idle_add(self._job_finished, on_done, r)

    def _job_finished(self, on_done, r):
        self._refresh_queue()
        on_done(r)
        return False

    def _refresh_queue(self):
        cur, waiting = getattr(self, "_job_cur", None), list(getattr(self, "_job_waiting", []))
        if cur or waiting:
            text = T("Processing: {name}", name=cur) if cur else T("Waiting to process")
            if waiting:
                text += "  ·  " + T("{n} waiting", n=len(waiting))
            self.queue_lbl.set_text(text)
            self.queue_spin.start(); self.queue_box.show()
        else:
            self.queue_spin.stop(); self.queue_box.hide()
        return False

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
        for w in (self.client_box, self.gloss_btn, self.focus_entry):
            w.set_sensitive(mode == "idle")
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
            try:
                stamp = NOTES_DIR.stat().st_mtime
            except OSError:
                stamp = 0
            if stamp != getattr(self, "_notes_stamp", stamp) and self.mode == "idle":
                self.load_meetings()
            self._notes_stamp = stamp
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
            self.set_mode("busy", T("Finishing the recording…"))
            threading.Thread(target=self._stop_worker, daemon=True).start()
        elif self.mode == "idle":
            if not self.is_ready() and not self.run_setup():
                return
            title = self.entry.get_text().strip() or "meeting"
            r = self.cli("start", title, *self._meta_args())
            if r.returncode == 0:
                self.started_at = time.time()
                self.set_mode("recording")
                self.notify(T("Recording started"), title)
            else:
                self.error_dialog(T("Could not start recording"), r.stderr or r.stdout)

    def _stop_worker(self):
        r = self.cli("stop", "--capture-only")
        GLib.idle_add(self._captured, r)

    def _captured(self, r):
        """The audio is safe; the window is free again while the notes are made."""
        self._live_text = None
        self.set_mode("idle")
        m = re.search(r"Queued: (\S+)", r.stdout)
        if r.returncode != 0 or not m:
            self.error_dialog(T("Could not stop the recording"), (r.stderr or r.stdout)[-800:])
            return False
        name = m.group(1)
        self.submit_job(re.sub(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_", "", name),
                        ("finish", name), self._stop_done)
        return False

    def _stop_done(self, r):
        self.load_meetings()
        if r.returncode == 0:
            self.notify(T("Notes ready"), T("Meeting notes have been written."))
            if self.mode == "idle" and self.listbox.get_row_at_index(0):   # never pull the view off a live recording
                self.listbox.select_row(self.listbox.get_row_at_index(0))
        else:
            self.error_dialog(T("Recording processed with errors"), (r.stderr or r.stdout)[-800:])
        return False

    # ---------- meetings ----------
    def load_meetings(self):
        self._meetings = msearch.load(NOTES_DIR, REC_DIR)
        self._refresh_clients()
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
        self._apply_search()

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

    def _apply_search(self):
        """Search notes and transcripts of every meeting, optionally within one client."""
        self._query = self.search.get_text().strip()
        self._client = self.client_filter.get_active_id() or ""
        self._hits = {h.meeting.name: h for h in msearch.search(self._meetings, self._query, self._client)}
        for row in self.listbox.get_children():
            path = getattr(row, "path", None)
            if path is None:
                continue
            hit = self._hits.get(path.stem)
            snip = getattr(row, "snip", None)
            if snip is not None:
                text = ""
                if self._query and hit and hit.snippet:
                    text = (T("transcript") + ": " if hit.where.startswith("transcript") else "") + hit.snippet
                snip.set_text(text.strip()); snip.set_visible(bool(text.strip()))
        self.listbox.invalidate_filter(); self.listbox.invalidate_sort()

    def _filter_row(self, row):
        path = getattr(row, "path", None)
        if path is None:
            return True
        if not self._query and not self._client:
            return True
        return path.stem in self._hits

    def _sort_rows(self, a, b):
        pa, pb = getattr(a, "path", None), getattr(b, "path", None)
        if pa is None or pb is None:
            return 0
        if self._query:
            sa = self._hits.get(pa.stem); sb = self._hits.get(pb.stem)
            ka, kb = (sa.score if sa else 0), (sb.score if sb else 0)
            if ka != kb:
                return -1 if ka > kb else 1
        return -1 if pa.stem > pb.stem else (1 if pa.stem < pb.stem else 0)

    def _refresh_clients(self):
        names = msearch.clients(self._meetings)
        current = self.client_filter.get_active_id() or ""
        self.client_filter.remove_all()
        self.client_filter.append("", T("All clients"))
        for n in names:
            self.client_filter.append(n, n)
        self.client_filter.set_active_id(current if current in names else "")
        self.client_filter.set_visible(bool(names))

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
        client = next((m.client for m in self._meetings if m.name == stem), "")
        if client:
            meta += "  ·  " + client
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
        row.snip = Gtk.Label(label="", xalign=0)
        row.snip.get_style_context().add_class("row-meta")
        row.snip.set_ellipsize(Pango.EllipsizeMode.END); row.snip.set_max_width_chars(34)
        row.snip.set_no_show_all(True); row.snip.hide()
        box.pack_start(row.snip, False, False, 0)
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
        words = msearch.terms(self._query) if getattr(self, "_query", "") else []
        if words:
            fc = self.webview.get_find_controller()
            GLib.timeout_add(400, lambda: (fc.search(words[0], WebKit2.FindOptions.CASE_INSENSITIVE
                                                     | WebKit2.FindOptions.WRAP_AROUND, 50), False)[1])

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
            ("Speakers", "Rename Speaker 1, Speaker 2… to the real names, in the transcript and the notes", self.on_speakers),
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
        label = f"{T(busy_text).rstrip('…')} · " + re.sub(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_", "", args[1] if len(args) > 1 else "")
        self.submit_job(label, args, lambda r: self._action_done(r, then_select))

    def _action_done(self, r, then_select):
        if r.returncode != 0:
            self.error_dialog(T("The action failed"), (r.stderr or r.stdout)[-800:])
        keep = then_select
        if keep == "__renamed__":
            m = re.search(r"Renamed to: (\S+)", r.stdout)
            keep = m.group(1) if m else (self.selected.stem if self.selected else None)
        self.selected = None
        self.load_meetings()
        if keep and self.mode == "idle":
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

    def on_speakers(self):
        if not self.selected:
            return
        name = self.selected.stem
        r = self.cli("speakers", name)
        rows = [ln.split("\t") for ln in r.stdout.splitlines() if "\t" in ln]
        if r.returncode != 0 or not rows:
            self.error_dialog(T("Could not rename the speakers"), (r.stderr or r.stdout)[-400:])
            return
        d = Gtk.Dialog(title=T("Rename speakers"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Rename"), Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area(); box.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(box.props, m, 14)
        hint = Gtk.Label(label=T("Type the real name next to each speaker; leave it empty to keep it. "
                                 "Two speakers with the same name are merged."), xalign=0, wrap=True)
        hint.set_max_width_chars(48); hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        entries = []
        for i, (who, n) in enumerate(rows):
            lbl = Gtk.Label(label=f"{who}  ·  {n} {T('lines')}", xalign=0)
            e = Gtk.Entry(placeholder_text=who, activates_default=True); e.set_width_chars(22)
            grid.attach(lbl, 0, i, 1, 1); grid.attach(e, 1, i, 1, 1)
            entries.append((who, e))
        box.pack_start(grid, False, False, 0)
        d.show_all()
        resp = d.run()
        pairs = [f"{who}={e.get_text().strip()}" for who, e in entries if e.get_text().strip()]
        d.destroy()
        if resp != Gtk.ResponseType.OK or not pairs:
            return
        r = self.cli("speakers", name, *pairs)
        if r.returncode != 0:
            self.error_dialog(T("Could not rename the speakers"), (r.stderr or r.stdout)[-400:])
            return
        self.notify(T("Speakers renamed"), "")
        self.selected = None
        self.load_meetings()
        for row in self.listbox.get_children():
            if getattr(row, "path", None) and row.path.stem == name:
                self.listbox.select_row(row)
                break
        self._refresh_actions()

    def on_export_menu(self):
        if not self.selected:
            return
        menu = Gtk.Menu()
        for ext, label in (("pdf", "PDF (.pdf)"), ("docx", "Word (.docx)"), ("md", "Markdown (.md)")):
            item = Gtk.MenuItem(label=T(label))
            item.connect("activate", lambda _i, e=ext: self.on_export(e))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        obs = Gtk.MenuItem(label=T("Obsidian note"))
        obs.connect("activate", lambda *_: self.on_obsidian())
        menu.append(obs)
        pick = Gtk.MenuItem(label=T("Choose the Obsidian vault…"))
        pick.connect("activate", lambda *_: self.pick_vault())
        menu.append(pick)
        menu.append(Gtk.SeparatorMenuItem())
        tr = Gtk.MenuItem(label=T("Send action items to Trello…"))
        tr.connect("activate", lambda *_: self.on_trello())
        menu.append(tr)
        trl = Gtk.MenuItem(label=T("Trello: choose the list…"))
        trl.connect("activate", lambda *_: self.trello_pick_list())
        menu.append(trl)
        menu.show_all()
        menu.popup_at_widget(self.action_btns[5], Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def pick_vault(self):
        d = Gtk.FileChooserDialog(title=T("Choose the Obsidian vault"), transient_for=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Select"), Gtk.ResponseType.OK)
        resp = d.run(); path = d.get_filename(); d.destroy()
        if resp != Gtk.ResponseType.OK or not path:
            return False
        r = self.cli("config", "obsidian_vault", path)
        if r.returncode != 0:
            self.error_dialog(T("Could not save the settings"), r.stderr or r.stdout)
            return False
        return True

    def on_obsidian(self):
        """Save the open meeting as a note in the Obsidian vault (asks for the vault the first time)."""
        if not self.selected:
            return
        if not self._cfg("obsidian_vault", "") and not self.pick_vault():
            return
        name = self.selected.stem
        r = self.cli("obsidian", name)
        if r.returncode != 0:
            self.error_dialog(T("Could not export to Obsidian"), (r.stderr or r.stdout)[-600:])
            return
        lines = r.stdout.strip().splitlines()
        self.notify(T("Saved in Obsidian"), Path(lines[0]).name if lines else "")

    # ---------- Trello: action items to cards (opt-in; sends the chosen text to Trello) ----------
    def trello_connect(self):
        d = Gtk.Dialog(title=T("Connect to Trello"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Connect"), Gtk.ResponseType.OK)
        area = d.get_content_area(); area.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(area.props, m, 14)
        info = Gtk.Label(label=T("Create an API key and a token on Trello's page for developers, and paste them here. "
                                 "They are kept in a file only you can read. Nothing is sent to Trello until you "
                                 "send action items."), xalign=0, wrap=True)
        info.set_max_width_chars(60)
        area.pack_start(info, False, False, 0)
        page = Gtk.Button(label=T("Open the Trello page"))
        page.connect("clicked", lambda *_: subprocess.Popen(
            ["xdg-open", "https://trello.com/power-ups/admin"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        area.pack_start(page, False, False, 0)
        key = Gtk.Entry(); key.set_placeholder_text(T("API key"))
        token = Gtk.Entry(); token.set_placeholder_text(T("Token")); token.set_visibility(False)
        area.pack_start(key, False, False, 0); area.pack_start(token, False, False, 0)
        d.show_all()
        resp = d.run(); k, t = key.get_text().strip(), token.get_text().strip(); d.destroy()
        if resp != Gtk.ResponseType.OK or not (k and t):
            return False
        r = self.cli("trello", "login", input=f"{k}\n{t}\n", timeout=60)      # through stdin, never as arguments
        if r.returncode != 0:
            self.error_dialog(T("Could not connect to Trello"), r.stderr or r.stdout)
            return False
        return True

    def trello_pick_list(self):
        if self.cli("trello", "status", timeout=60).returncode != 0 and not self.trello_connect():
            return False
        boards = [ln.split("\t", 1) for ln in self.cli("trello", "boards", timeout=60).stdout.splitlines() if "\t" in ln]
        if not boards:
            self.error_dialog(T("Trello"), T("No boards found on this account."))
            return False
        d = Gtk.Dialog(title=T("Where should the cards go?"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Select"), Gtk.ResponseType.OK)
        area = d.get_content_area(); area.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(area.props, m, 14)
        bbox, lbox = Gtk.ComboBoxText(), Gtk.ComboBoxText()
        for bid, name in boards:
            bbox.append(bid, name)

        def load_lists(*_):
            lbox.remove_all()
            bid = bbox.get_active_id()
            if bid:
                for ln in self.cli("trello", "lists", bid, timeout=60).stdout.splitlines():
                    if "\t" in ln:
                        lid, name = ln.split("\t", 1); lbox.append(lid, name)
                lbox.set_active(0)
        bbox.connect("changed", load_lists)
        area.pack_start(Gtk.Label(label=T("Board"), xalign=0), False, False, 0); area.pack_start(bbox, False, False, 0)
        area.pack_start(Gtk.Label(label=T("List"), xalign=0), False, False, 0); area.pack_start(lbox, False, False, 0)
        bbox.set_active(0)
        d.show_all()
        resp = d.run(); lid, lname = lbox.get_active_id(), lbox.get_active_text(); d.destroy()
        if resp != Gtk.ResponseType.OK or not lid:
            return False
        r = self.cli("trello", "use", lid, lname or "")
        if r.returncode != 0:
            self.error_dialog(T("Trello"), r.stderr or r.stdout)
            return False
        return True

    def on_trello(self):
        if not self.selected:
            return
        name = self.selected.stem
        if self.cli("trello", "status", timeout=60).returncode != 0 and not self.trello_connect():
            return
        if not self._cfg("trello_list", "") and not self.trello_pick_list():
            return
        r = self.cli("trello", "actions", name)
        try:
            acts = json.loads(r.stdout)
        except ValueError:
            self.error_dialog(T("Trello"), (r.stderr or r.stdout)[-400:])
            return
        if not acts:
            self.error_dialog(T("Trello"), T("This meeting has no action items."))
            return
        d = Gtk.Dialog(title=T("Send action items to Trello"), transient_for=self, modal=True)
        d.add_button(T("Cancel"), Gtk.ResponseType.CANCEL)
        d.add_button(T("Create cards"), Gtk.ResponseType.OK)
        area = d.get_content_area(); area.set_spacing(6)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(area.props, m, 14)
        target = self._cfg("trello_list_name", "") or self._cfg("trello_list", "")
        head = Gtk.Label(label=T("Cards will be created in “{list}”. The text of the checked items and the "
                                 "meeting title are sent to Trello.", list=target), xalign=0, wrap=True)
        head.set_max_width_chars(70)
        area.pack_start(head, False, False, 0)
        checks = []
        for a in acts:
            label = (f"{a['owner']}: " if a.get("owner") else "") + a["text"]
            cb = Gtk.CheckButton(label=label + (f"  ({T('already sent')})" if a.get("sent") else ""))
            cb.get_child().set_line_wrap(True); cb.get_child().set_max_width_chars(80)
            cb.set_active(not a.get("sent")); cb.set_sensitive(not a.get("sent"))
            area.pack_start(cb, False, False, 0); checks.append((a["i"], cb))
        d.show_all()
        resp = d.run()
        chosen = [str(i) for i, cb in checks if cb.get_active() and cb.get_sensitive()]
        d.destroy()
        if resp != Gtk.ResponseType.OK or not chosen:
            return

        def done(res):
            made = res.stdout.count("created:")
            if res.returncode == 0:
                self.notify(T("Trello"), T("{n} cards created.", n=made))
            else:
                self.error_dialog(T("Some cards were not created"), (res.stderr or res.stdout)[-500:])
        self.submit_job(T("Trello: {title}", title=name[17:] or name), ("trello", "send", name, "--only", ",".join(chosen)), done)

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

        # ---- keyboard shortcut (GNOME custom shortcut that runs `minuta toggle`)
        current_keys = (lambda r: r.stdout.strip() if r.returncode == 0 else "")(self.cli("shortcut", "show"))
        box.pack_start(heading("Keyboard shortcut"), False, False, 0)
        keys_entry = Gtk.Entry(text=current_keys, placeholder_text="<Super><Alt>r")
        box.pack_start(keys_entry, False, False, 0)
        box.pack_start(note("Starts and stops a recording from anywhere, for example <Super><Alt>r. "
                            "Leave it empty for none. Needs GNOME."), False, False, 0)

        # ---- notes writer
        box.pack_start(heading("Who writes the notes"), False, False, 0)
        current_notes_model = self._cfg("notes_model", "small")
        notes_model_box = combo([("small", "Local model: small (0.5 GB, fast)"),
                                 ("medium", "Local model: medium (2 GB, better summaries)")],
                                current_notes_model, "small")
        box.pack_start(notes_model_box, False, False, 0)
        box.pack_start(note("Used when the notes are written on this computer. The medium model "
                            "downloads ~2 GB once and needs about 3 GB of free memory."), False, False, 0)
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
            "notes_model": notes_model_box.get_active_id() or current_notes_model,
            "notes_provider": next((k for k, rb in radios.items() if rb.get_active()), "local"),
        }
        new_keys = keys_entry.get_text().strip()
        d.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        if new_keys != current_keys:
            r = self.cli("shortcut", "set", new_keys) if new_keys else self.cli("shortcut", "remove")
            if r.returncode != 0:
                self.error_dialog(T("Could not set the shortcut"), (r.stderr or r.stdout)[-400:])
        for key, val in new.items():
            r = self.cli("config", key, val)
            if r.returncode != 0:
                self.error_dialog(T("Could not save the settings"), r.stderr or r.stdout)
                return
        if (new["whisper_model"] != current_model or new["notes_model"] != current_notes_model
                or (new["diarize"] == "on" and not current_diarize)):
            self.run_setup()        # downloads the speech / speaker models when they are missing

    # ---------- helpers ----------
    def notify(self, summary, body):
        try:
            n = Notify.Notification.new(summary, body, "minuta")
            n.show()
        except Exception:
            pass

    def error_dialog(self, primary, detail):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.CLOSE, text=primary)
        d.format_secondary_text((detail or "").strip()[:600])
        d.run(); d.destroy()


class MinutaApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.bcocheto.Minuta")

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_prgname("io.github.bcocheto.Minuta")
        Gtk.Window.set_default_icon_name("minuta")
        Notify.init("Minuta")
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", IS_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.get_active_window() or MinutaWindow(self)
        win.show_all()
        win.present()


if __name__ == "__main__":
    import sys
    sys.exit(MinutaApp().run(sys.argv))

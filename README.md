# MeetingInsights — AI Note Taker for Linux

Record a meeting (or import an audio/video file) and get a transcript plus structured
minutes. Speech recognition and note writing run on your machine: no account, no API key,
no upload. An external writer for the notes (Claude Code or Gemini CLI) exists, but it is
off unless you turn it on.

A GTK desktop app and a CLI. Audio is captured with PulseAudio/PipeWire, transcribed by
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (on the NVIDIA GPU when there
is one) and summarised by a small local model through
[llama.cpp](https://github.com/ggml-org/llama.cpp).

## What you get

- **Record or import.** Capture the microphone and the call audio together, or drop in a
  recording (any audio or video file).
- **Live transcription** while the meeting runs, so stopping is nearly instant. Writing the
  notes happens in a background queue: the window stays free, and you can start the next
  recording while the last one is still being processed.
- **Input meters** for the microphone and the call audio while recording, with a warning if
  one of them stops picking up sound, so a dead input is caught in seconds, not after the meeting.
- **Who said what.** You, and each voice on the far end (*Participant 1, 2…*).
- **Notes**: summary, action items with owners, decisions and open questions, in the
  language of the meeting (Portuguese and English).
- **Per-meeting context**: a *client* with a saved glossary of names and terms, and a
  *focus* ("what matters in this meeting") that gets its own **In focus** section.
- **Per-meeting actions**: rename, rewrite the notes, transcribe again, edit the
  transcript, delete; export to Markdown, Word (`.docx`) or PDF.
- **Crash recovery**: a recording cut short (crash, power loss) is finished on the next
  launch, and audio that never got notes is offered for processing.

## How it works

| Part of the notes | Produced by |
|---|---|
| Transcript | faster-whisper, local, GPU when available |
| "You" vs. the far end | audio routing (separate channels) |
| *Participant 1, 2…* on the far end | offline speaker diarization (sherpa-onnx) |
| Questions, decisions, action items | pattern rules over the transcript (Portuguese and English) |
| Action-item owners | the speaker labels |
| **In focus** section | keyword match of your focus against the transcript |
| Prose summary | a local language model (small or medium), or Claude Code / Gemini CLI if you opt in |

**Why the speakers are reliable.** Your microphone is recorded to the left channel and
everything you hear to the right, and each channel is transcribed separately, so "You" is
exact. The far end shares one channel; a diarization model splits it by voice, cutting
where the voice changes. Action-item owners are read off those labels. The language model
is never asked who committed to what, so it cannot invent a participant.

**Why a tiny model is enough.** Structure, classification and attribution are done in
code, and the model only writes short prose summaries. In testing, moving classification
out of the model and into rules fixed every misclassification and cut runtime by ~75%.
For richer summaries, choose the **medium** local model (3B: it also writes a short
overview at the top, and writes in the language of the meeting; about 4× slower on a CPU,
roughly 5 minutes for an 11-minute meeting on 8 cores), or switch the note writer to
Claude Code or Gemini CLI (see [Privacy](#privacy)).

## Requirements

- Linux with PulseAudio or PipeWire, `ffmpeg`, Python 3.9+
- A GPU is optional. Without one it runs on the CPU with the `small` model; with an NVIDIA
  GPU the installer adds the CUDA libraries and uses `large-v3-turbo`, which is several
  times faster (a 62-second recording takes about 4 s after the model loads).
- Disk: ~1.5 GB for the base models, plus ~1.6 GB for `large-v3-turbo` and ~46 MB for the
  diarization model, all downloaded once. About 650 MB of RAM while writing notes with the small model, about 3 GB with the medium one.

## Install

**Debian / Ubuntu** — the package bundles the llama.cpp runtime, so nothing has to be compiled:

```sh
sudo apt install ./meetinginsights_0.1.1_amd64.deb
meetinginsights setup      # prepares Python and downloads the models, once
```

**From source** (any distro):

```sh
./install.sh               # installs to ~/.local
meetinginsights setup
```

The source install needs llama.cpp, built once:

```sh
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF
cmake --build build -j --target llama-app
mkdir -p ~/.local/share/meetinginsights/llama
cp build/bin/llama build/bin/*.so* ~/.local/share/meetinginsights/llama/
```

Upstream's prebuilt binaries require glibc 2.34, which rules out Ubuntu 20.04 and 22.04 —
which is why the `.deb` ships its own build.

## Use

Open **MeetingInsights** from the applications menu. In *New meeting* choose **Record**
(type a title, optionally a client and a focus) or **Import a file**. When you stop, the
notes appear in the list.

From the terminal:

```sh
meetinginsights start "Weekly sync" --client "Acme" --focus "pricing: 8% or 10% down payment?"
meetinginsights stop                       # transcribes, then writes the notes
meetinginsights status

meetinginsights import call.mp4 "Kickoff" --client "Acme"
meetinginsights notes <transcript.txt>     # regenerate notes from a transcript
meetinginsights reprocess <name> [--notes-only] [--client N] [--focus T]
meetinginsights rename <name> "New title"
meetinginsights export <name> <md|docx|pdf> [file] [--no-transcript]
meetinginsights delete <name>
meetinginsights recover [--list]           # finish an interrupted recording
```

`<name>` is the file stem, e.g. `2026-11-09_14-36_weekly-sync`. Run `meetinginsights help`
for the full list.

Notes land in `~/MeetingNotes/`; audio and transcripts in
`~/.local/share/meetinginsights/rec/`.

### Clients and glossaries

A glossary is the names and terms a client uses (people, products, jargon). It is added to
the speech recognizer's prompt and given to the note writer, which fixes near-miss
spellings. In the app, type the client in *New meeting* and press **Glossary**; from the
CLI:

```sh
meetinginsights client set "Acme" "Be In Rio, Lumière, own use, IA Zap"
meetinginsights client list | show "Acme" | rm "Acme"
```

The *focus* is free text for one meeting. It steers the summary and fills the **In focus**
section with the lines of the transcript that mention it. It is not an instruction to the
transcriber; use the glossary or the *Initial prompt* setting for that.

## Settings

Open **Settings** in the app, or use `meetinginsights config [key [value]]` and
`meetinginsights language`.

| Setting | Values | Default |
|---|---|---|
| Spoken language | `system` (follows the OS), `auto`, or a code such as `pt`, `en` | `system` |
| Transcription model | `small`, `medium`, `large-v3-turbo` | `large-v3-turbo` with GPU libraries, else `small` |
| Processor | `auto` (GPU when usable), `cpu` | `auto` |
| Who writes the notes | `local`, `claude-code`, `gemini-cli` | `local` |
| Local summary model | `notes_model`: `small` (0.5B, 0.5 GB) or `medium` (3B, 2 GB) | `small` |
| Tell voices apart | `diarize` on/off, `speakers` 0 (auto) to 8 | on |
| Initial prompt | names and jargon to help spelling (`prompt`, up to 500 characters) | empty |
| Accuracy | `beam` 1 (fast) to 10 | 5 |
| Even out volume / threads | `normalize` on/off, `threads` 0 = auto | off / 0 |

Environment variables override the settings file (`~/.config/meetinginsights/config`):

| Variable | Meaning |
|---|---|
| `MEETINGINSIGHTS_OUT` | where notes are written (default `~/MeetingNotes`) |
| `MEETINGINSIGHTS_HOME` | where models, audio and transcripts live |
| `MEETINGINSIGHTS_WHISPER_MODEL` | transcription model |
| `MEETINGINSIGHTS_LLM_MODEL` | any GGUF chat model for the local note writer |
| `MEETINGINSIGHTS_YOU` / `MEETINGINSIGHTS_THEM` | channel labels |
| `MEETINGINSIGHTS_LIVE` | `0` turns off live transcription |

## Privacy

- Audio, transcripts and notes stay on your machine, in folders only your user can read.
- Models are downloaded once, during `setup` (or the first use of a new model). After that
  the transcriber loads them from disk and makes no network calls.
- **Opt-in exception:** if you pick `claude-code` or `gemini-cli` as the note writer, the
  **transcript is sent to that service** to write the notes. The app uses the CLI you
  already have installed and logged in, and never sees your credentials. Notes written
  this way say so at the top. Leave the setting on `local` to keep everything offline.

## Recording consent

Recording a conversation without telling the other participants is illegal in many places.
`meetinginsights start` prints a reminder; please honour it.

## Tests

```sh
python3 -m unittest discover -s tests
```

Covers note classification, focus matching, the external writer, the CLI (glossaries,
interrupted recordings, renames) and word error rate. To guard transcription quality when
you change the pipeline, point it at a recording and its reference text:

```sh
MI_E2E_AUDIO=talk.wav MI_E2E_REFERENCE=talk.txt MI_E2E_MAX_WER=0.20 \
  ~/.local/share/meetinginsights/venv/bin/python -m unittest tests.test_e2e
```

## Licence

MIT — see `LICENSE`.

## Links

- Source: https://github.com/techbysaurabh/meetinginsights-linux
- The iOS sibling, *MeetingInsights: AI Minutes*, is on the App Store — this is the Linux
  counterpart and shares its icon and design language.

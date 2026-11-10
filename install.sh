#!/bin/bash
# Install Minuta into ~/.local (no root required).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
SHARE="$PREFIX/share/minuta"
DATA="$HOME/.local/share/minuta"

echo "Installing Minuta to $PREFIX"

missing=()
for c in parec ffmpeg ffprobe python3; do command -v "$c" >/dev/null || missing+=("$c"); done
python3 -c "import gi" 2>/dev/null || missing+=("python3-gi")
if ((${#missing[@]})); then
    echo "Missing dependencies: ${missing[*]}" >&2
    echo "On Debian/Ubuntu:" >&2
    echo "  sudo apt install pulseaudio-utils ffmpeg python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 gir1.2-notify-0.7 python3-venv" >&2
    exit 1
fi

# The app used to be called MeetingInsights. Its models, environment and recordings lived in the
# same folder as its program files, so move that folder as a whole (never delete it) and keep the settings.
OLD_DATA="$HOME/.local/share/meetinginsights"
OLD_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/meetinginsights"; NEW_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/minuta"
if [[ -d "$OLD_DATA" && ! -e "$DATA" ]]; then
    mv "$OLD_DATA" "$DATA" && echo "Moved your data from $OLD_DATA to $DATA"
fi
if [[ -d "$OLD_CFG" && ! -e "$NEW_CFG" ]]; then
    mv "$OLD_CFG" "$NEW_CFG" && echo "Moved your settings from $OLD_CFG to $NEW_CFG"
fi
# old program files only: lib/ and gui/ hold code, never data
rm -rf "$PREFIX/share/meetinginsights/lib" "$PREFIX/share/meetinginsights/gui"
rmdir "$PREFIX/share/meetinginsights" 2>/dev/null || true
rm -f "$PREFIX/bin/meetinginsights" "$PREFIX/bin/meetinginsights-gui" \
      "$PREFIX/share/applications/page.saurabh.MeetingInsights.desktop" "$PREFIX/share/applications/meetinginsights.desktop"
find "$PREFIX/share/icons/hicolor" -name 'meetinginsights.png' -delete 2>/dev/null || true
# replace our own code folders cleanly, whatever a previous version left in them
rm -rf "$SHARE/lib" "$SHARE/gui"

mkdir -p "$SHARE" "$PREFIX/bin" "$PREFIX/share/applications" "$DATA/models"
cp -r "$SRC/lib" "$SRC/gui" "$SHARE/"
find "$SHARE" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
install -m755 "$SRC/bin/minuta" "$PREFIX/bin/minuta"

cat > "$PREFIX/bin/minuta-gui" <<GUI
#!/bin/bash
exec python3 "$SHARE/gui/minuta_gui.py" "\$@"
GUI
chmod +x "$PREFIX/bin/minuta-gui"

for sz in 16 22 24 32 48 64 128 256 512; do
    d="$PREFIX/share/icons/hicolor/${sz}x${sz}/apps"
    mkdir -p "$d"
    install -m644 "$SRC/icons/${sz}x${sz}/minuta.png" "$d/minuta.png" 2>/dev/null || true
done
gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

# The file name must equal the GTK application id, or Wayland shows a generic dock icon.
rm -f "$PREFIX/share/applications/minuta.desktop"
sed "s|^Exec=.*|Exec=$PREFIX/bin/minuta-gui|" "$SRC/io.github.bcocheto.Minuta.desktop" \
    > "$PREFIX/share/applications/io.github.bcocheto.Minuta.desktop"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true

if [[ ! -x "$DATA/venv/bin/python" ]]; then
    echo "Creating the Python environment (this takes a minute)..."
    python3 -m venv "$DATA/venv"
    "$DATA/venv/bin/python" -m pip install -q --upgrade pip
    "$DATA/venv/bin/python" -m pip install -q faster-whisper python-docx reportlab sherpa-onnx
    # NVIDIA GPU present: CUDA libraries inside this environment only, for faster transcription
    if command -v nvidia-smi >/dev/null 2>&1; then
        "$DATA/venv/bin/python" -m pip install -q nvidia-cublas-cu12 nvidia-cudnn-cu12 || true
    fi
fi

if [[ ! -x "$DATA/llama/llama" ]]; then
    echo
    echo "The llama.cpp runtime is not installed yet."
    echo "Build it once with:"
    echo "  git clone --depth 1 https://github.com/ggml-org/llama.cpp"
    echo "  cd llama.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF"
    echo "  cmake --build build -j --target llama-app"
    echo "  mkdir -p $DATA/llama && cp build/bin/llama build/bin/*.so* $DATA/llama/"
fi

echo
echo "Installed. Next:"
echo "  minuta setup     # download the models (~1.5 GB, one time)"
echo "  minuta start \"My meeting\""
echo
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "Note: add $PREFIX/bin to your PATH." ;; esac

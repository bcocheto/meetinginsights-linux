#!/bin/bash
# Build the Minuta .deb.
#
# Requires a compiled llama.cpp runtime; point LLAMA_DIR at a directory holding
# the `llama` binary and its .so files (see README for the build commands).
# The runtime is bundled so users never have to compile anything — upstream's
# prebuilt binaries need glibc 2.34, which excludes Ubuntu 20.04 and 22.04.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="${VER:-0.1.0}"
LLAMA_DIR="${LLAMA_DIR:-$HOME/.local/share/minuta/llama}"
OUT="${OUT:-$SRC/dist}"
B="$OUT/minuta_${VER}_amd64"

[[ -x "$LLAMA_DIR/llama" ]] || { echo "no llama runtime at $LLAMA_DIR" >&2; exit 1; }
command -v fakeroot >/dev/null || { echo "need fakeroot" >&2; exit 1; }

rm -rf "$B"; mkdir -p "$B"/{DEBIAN,usr/bin,usr/share/minuta,usr/lib/minuta/llama,usr/share/applications,usr/share/doc/minuta,usr/share/man/man1}

cp -r "$SRC/lib" "$SRC/gui" "$B/usr/share/minuta/"
# bytecode from a local test run must not ship in the package
find "$B/usr/share/minuta" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$B/usr/share/minuta" -name '*.py[co]' -delete 2>/dev/null || true
install -m755 "$SRC/bin/minuta" "$B/usr/bin/minuta"
printf '#!/bin/bash\nexec python3 /usr/share/minuta/gui/minuta_gui.py "$@"\n' \
    > "$B/usr/bin/minuta-gui"

install -m755 "$LLAMA_DIR/llama" "$B/usr/lib/minuta/llama/llama"
for so in "$LLAMA_DIR"/*.so*; do install -m644 "$so" "$B/usr/lib/minuta/llama/"; done

# strip build-machine rpaths and debug symbols: lintian errors otherwise, and
# a baked-in rpath would send the loader looking in the build tree at runtime
if command -v patchelf >/dev/null; then
    for f in "$B"/usr/lib/minuta/llama/*; do patchelf --remove-rpath "$f" 2>/dev/null || true; done
elif command -v pip3 >/dev/null && pip3 install --quiet --user patchelf 2>/dev/null \
     && [ -x "$HOME/.local/bin/patchelf" ]; then
    for f in "$B"/usr/lib/minuta/llama/*; do "$HOME/.local/bin/patchelf" --remove-rpath "$f" 2>/dev/null || true; done
else
    echo "warning: patchelf unavailable; verify with 'lintian' that no rpath survived" >&2
fi
strip --strip-unneeded "$B"/usr/lib/minuta/llama/* 2>/dev/null || true

for sz in 16 22 24 32 48 64 128 256 512; do
    d="$B/usr/share/icons/hicolor/${sz}x${sz}/apps"; mkdir -p "$d"
    install -m644 "$SRC/icons/${sz}x${sz}/minuta.png" "$d/minuta.png"
done
install -m644 "$SRC/io.github.bcocheto.Minuta.desktop" "$B/usr/share/applications/io.github.bcocheto.Minuta.desktop"
install -m644 "$SRC/README.md" "$B/usr/share/doc/minuta/README.md"
install -m644 "$SRC/README.pt-BR.md" "$B/usr/share/doc/minuta/README.pt-BR.md"
install -m644 "$SRC/LICENSE"  "$B/usr/share/doc/minuta/copyright"
gzip -9nc "$SRC/packaging/minuta.1" > "$B/usr/share/man/man1/minuta.1.gz"
echo ".so man1/minuta.1" | gzip -9n > "$B/usr/share/man/man1/minuta-gui.1.gz"
printf 'minuta (%s) stable; urgency=low\n\n  * Release %s.\n\n -- Breno Cocheto <breno.cocheto@gmail.com>  %s\n' \
    "$VER" "$VER" "$(date -R)" | gzip -9n > "$B/usr/share/doc/minuta/changelog.gz"

install -m755 "$SRC/packaging/debian/postinst" "$B/DEBIAN/postinst"
install -m755 "$SRC/packaging/debian/postrm"   "$B/DEBIAN/postrm"

find "$B" -path "*/DEBIAN" -prune -o -type d -print0 | xargs -0 chmod 755
find "$B" -path "*/DEBIAN" -prune -o -type f -print0 | xargs -0 chmod 644
chmod 755 "$B/usr/bin/minuta" "$B/usr/bin/minuta-gui" \
          "$B/usr/lib/minuta/llama/llama" "$B/DEBIAN/postinst" "$B/DEBIAN/postrm"

sed -e "s|^Version:.*|Version: $VER|" \
    -e "s|^Installed-Size:.*|Installed-Size: $(du -sk "$B" | cut -f1)|" \
    "$SRC/packaging/debian/control" > "$B/DEBIAN/control"

fakeroot dpkg-deb --build -Zxz "$B"
command -v lintian >/dev/null && lintian "$B.deb" || true
echo "built: $B.deb"

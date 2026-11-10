#!/bin/bash
# Regenerates python-deps.json: the Python wheels the Flatpak installs, pinned with URLs and sha256.
# Resolved inside the same GNOME runtime the app runs on, so the wheels match its Python.
#   packaging/flatpak/make-python-deps.sh [runtime-version]      (default: 50; needs network)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RT="${1:-50}"
PKGS="faster-whisper python-docx reportlab sherpa-onnx numpy"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
flatpak run --no-documents-portal --share=network --filesystem="$TMP" --command=sh "org.gnome.Sdk//$RT" -c \
    "cd '$TMP' && python3 -m pip install --dry-run --ignore-installed --only-binary=:all: --report report.json -q $PKGS"
python3 - "$TMP/report.json" "$HERE/python-deps.json" <<'PY'
import json, sys
rep = json.load(open(sys.argv[1]))
wheels = sorted(rep["install"], key=lambda i: i["metadata"]["name"].lower())
sources, names = [], []
for i in wheels:
    url, sha = i["download_info"]["url"], i["download_info"]["archive_info"]["hashes"]["sha256"]
    sources.append({"type": "file", "url": url, "sha256": sha})
    names.append(url.rsplit("/", 1)[1])
module = {
    "name": "python-deps",
    "buildsystem": "simple",
    "build-commands": ['pip3 install --verbose --exists-action=i --ignore-installed --no-index --find-links="file://${PWD}" '
                       '--prefix=${FLATPAK_DEST} --no-deps ' + " ".join(names)],
    "sources": sources,
}
json.dump(module, open(sys.argv[2], "w"), indent=2); open(sys.argv[2], "a").write("\n")
print(f"{len(names)} wheels pinned")
PY

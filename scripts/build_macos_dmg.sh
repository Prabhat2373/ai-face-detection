#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r python_recognizer/requirements.txt
python3 -m pip install PySide6 pyinstaller

rm -rf build dist/FaceAgent dist/FaceAgent.app dist/FaceAgent.dmg dist/FaceAgent.pkg dist/dmg dist/pkg-root
python3 scripts/prepare_macos_ffmpeg.py
pyinstaller FaceAgent.spec --noconfirm --clean

mkdir -p dist/dmg
cp -R dist/FaceAgent.app dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname FaceAgent -srcfolder dist/dmg -ov -format UDZO dist/FaceAgent.dmg

mkdir -p dist/pkg-root/Applications
cp -R dist/FaceAgent.app dist/pkg-root/Applications/
pkgbuild \
    --root dist/pkg-root \
    --install-location / \
    --identifier com.faceagent.desktop \
    --version 1.0.0 \
    dist/FaceAgent.pkg

echo "Built dist/FaceAgent.dmg and dist/FaceAgent.pkg"

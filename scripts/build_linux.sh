#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r python_recognizer/requirements.txt
python3 -m pip install PySide6 pyinstaller

pyinstaller FaceAgent.spec --noconfirm

echo "Built dist/FaceAgent/FaceAgent"

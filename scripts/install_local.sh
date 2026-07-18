#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-$(pwd)}"
SERVICE_NAME="rtsp-face-detection"
NODE_BIN="$(command -v node)"
PYTHON_BIN="$(command -v python3)"

if [[ -z "${NODE_BIN}" || -z "${PYTHON_BIN}" ]]; then
  echo "node and python3 are required."
  exit 1
fi

cat <<EOF
Local deployment helper
=======================

Application directory: ${APP_DIR}

Suggested systemd unit:
[Unit]
Description=RTSP Face Detection
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${NODE_BIN} ${APP_DIR}/dist/server.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target

Python recognizer can be run separately with:
${PYTHON_BIN} ${APP_DIR}/python_recognizer/app.py

If you want me to generate a real system service file, I can add one for Linux, macOS, or Windows next.
EOF

#!/bin/bash
set -euo pipefail

PROJECT_DIR=/home/christiangeer/fantasy-scoreboard
SERVICE_SOURCE="$PROJECT_DIR/deploy/fantasy-scoreboard.service"
SERVICE_DEST=/etc/systemd/system/fantasy-scoreboard.service

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as christiangeer; it will use sudo where needed." >&2
    exit 1
fi

cd "$PROJECT_DIR"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-pi.txt
chmod +x scripts/run-physical-scoreboard scripts/install_pi_service.sh
sudo install -m 0644 "$SERVICE_SOURCE" "$SERVICE_DEST"
sudo systemctl daemon-reload
sudo systemd-analyze verify "$SERVICE_DEST"
sudo systemctl disable fantasy-scoreboard.service

echo "Installed manual-only fantasy-scoreboard.service"
echo "Start: sudo systemctl start fantasy-scoreboard.service"
echo "Stop:  sudo systemctl stop fantasy-scoreboard.service"
echo "Logs:  journalctl -u fantasy-scoreboard.service -f"

#!/usr/bin/env bash
set -euo pipefail

# Run on the Raspberry Pi from the rpi-server directory.
# Installs system packages, Python deps (uv), supervisor programs, and nginx config.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Installing system packages"
$SUDO apt-get update
$SUDO apt-get install -y supervisor nginx motion curl

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Syncing Python dependencies with uv"
cd "$PROJECT_DIR"
uv sync

VENV_PY="$PROJECT_DIR/.venv/bin/python"

echo "==> Installing supervisor config"
$SUDO cp "$PROJECT_DIR/supervisord.conf" /etc/supervisor/supervisord.conf
$SUDO mkdir -p /etc/supervisor/conf.d
for conf in colordetect netconman picocoms motion websockify control-api; do
  sed -e "s|/usr/bin/python3|$VENV_PY|" \
      -e "s|/home/space/.supervisor|$PROJECT_DIR|g" \
      -e "s|command=websockify|command=$PROJECT_DIR/.venv/bin/websockify|" \
      "$PROJECT_DIR/$conf.conf" | $SUDO tee "/etc/supervisor/conf.d/$conf.conf" >/dev/null
done

echo "==> Installing nginx config"
$SUDO cp "$PROJECT_DIR/nginx/nginx.conf" /etc/nginx/nginx.conf
$SUDO cp "$PROJECT_DIR/nginx/default" /etc/nginx/sites-available/default
$SUDO ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
$SUDO nginx -t

echo "==> Enabling and starting services"
$SUDO systemctl enable --now supervisor nginx
$SUDO systemctl restart supervisor nginx

echo "==> Done. Check with: sudo supervisorctl status"

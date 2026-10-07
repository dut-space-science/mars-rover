#!/usr/bin/env bash
set -euo pipefail

# Removes the supervisor programs and nginx site installed by install.sh.
# System packages (supervisor, nginx, motion) are left installed.

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Stopping services"
$SUDO systemctl stop supervisor || true
$SUDO systemctl disable supervisor || true

echo "==> Removing supervisor config"
for conf in colordetect netconman picocoms motion websockify control-api; do  # same list as install.sh
  $SUDO rm -f "/etc/supervisor/conf.d/$conf.conf"
done

$SUDO rm -f /etc/sudoers.d/rover-supervisorctl

echo "==> Removing nginx site"
$SUDO rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default
$SUDO rm -f /var/www/html/index.html
$SUDO systemctl restart nginx || true

echo "==> Done. To also remove packages: sudo apt-get purge supervisor nginx motion"

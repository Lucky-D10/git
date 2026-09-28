#!/bin/sh
# Run as the graphical login account, never as root. No network dependency.
set -eu
browser=$(command -v chromium || command -v chromium-browser || true)
[ -n "$browser" ] || { echo 'Chromium is required' >&2; exit 1; }
python3 /opt/focus/current/deploy/kiosk_boot.py &
boot_pid=$!
trap 'kill "$boot_pid" 2>/dev/null || true' EXIT HUP INT TERM
"$browser" --kiosk --no-first-run --noerrdialogs --app=http://127.0.0.1:8001
# A normal browser exit returns to the desktop for maintenance, without a loop.

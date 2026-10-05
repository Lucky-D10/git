#!/bin/sh
# Usage: sudo sh rollback.sh /opt/focus/releases/<previous-release>
# No files or records are deleted. Current DB schema is additive and compatible.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
target=$(readlink -f -- "${1:?previous release directory required}")
case "$target" in /opt/focus/releases/*) ;; *) echo 'Target outside releases' >&2; exit 2 ;; esac
[ -f "$target/app.py" ] && [ -x "$target/.venv/bin/python" ] || exit 2
previous=$(readlink -f /opt/focus/current)
systemctl stop focus-web.service
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p /var/lib/focus/rollback
cp /etc/focus/hardware.json "/var/lib/focus/rollback/config-$stamp.json"
python3 - /var/lib/focus/focus.sqlite3 "/var/lib/focus/rollback/database-$stamp.sqlite3" <<'PY'
import sqlite3, sys
from contextlib import closing
with closing(sqlite3.connect(sys.argv[1])) as source, closing(sqlite3.connect(sys.argv[2])) as dest:
    source.backup(dest)
PY
ln -sfn "$target" /opt/focus/current.next
mv -Tf /opt/focus/current.next /opt/focus/current
systemctl start focus-web.service
echo "Previous: $previous; now: $target. Check health; output stays inhibited."

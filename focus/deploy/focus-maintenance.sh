#!/bin/sh
set -eu
case "${1:-status}" in
  status) systemctl --no-pager status focus-web.service ;;
  logs) journalctl --no-pager -u focus-web.service -n "${2:-100}" ;;
  export) curl --fail http://127.0.0.1:8000/api/maintenance/logs -o "${2:-focus-logs.zip}" ;;
  stop) systemctl stop focus-web.service ;;
  restart) systemctl restart focus-web.service ;;
  *) echo "Usage: $0 status|logs [lines]|export [file]|stop|restart" >&2; exit 2 ;;
esac

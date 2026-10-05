"""Run after each real cold boot. Records once per Linux boot; never starts motors."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import platform
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('/var/lib/focus/cold-starts.jsonl'))
    parser.add_argument('--ui-confirmed', action='store_true', help='Operator has visually verified the usable kiosk page')
    args = parser.parse_args()
    boot_file = Path('/proc/sys/kernel/random/boot_id')
    if not boot_file.exists():
        parser.error('Requires the target Linux machine; desktop restarts are not cold boots')
    boot_id = boot_file.read_text().strip()
    rows = [json.loads(line) for line in args.output.read_text().splitlines()] if args.output.exists() else []
    if any(row['boot_id'] == boot_id for row in rows):
        parser.error('This boot is already recorded')
    started = time.monotonic()
    ready, error = False, None
    while time.monotonic() - started < 120:
        try:
            with urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                health = json.load(response)
                ready = health.get('ready') and health.get('mode') == 'hardware'
                if ready:
                    break
        except (OSError, ValueError) as exc:
            error = str(exc)
        time.sleep(1)
    row = dict(boot_id=boot_id, date=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
               hardware_service_ready=bool(ready), ui_confirmed=args.ui_confirmed,
               observed_uptime_seconds=float(Path('/proc/uptime').read_text().split()[0]),
               probe_wait_seconds=time.monotonic()-started, error=None if ready else error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('a', encoding='utf-8') as output:
        output.write(json.dumps(row, ensure_ascii=False)+'\n')
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0 if ready and args.ui_confirmed else 1


if __name__ == '__main__':
    raise SystemExit(main())

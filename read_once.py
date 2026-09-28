# Linux aarch64（树莓派 / RK 等）+ CPython 3.11
# 本目录自带 wheel，在虚拟环境里安装后再跑：
#
#   python3 -m venv .venv
#   source .venv/bin/activate
#   pip install attention_usb-1.0.0-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl
#   python read_once.py
#   python read_once.py /dev/ttyACM0

import sys

try:
    from attention_usb import HeadbandUsb, list_ports_adapter
except ImportError as exc:
    raise SystemExit(
        "attention_usb 未安装或与当前 Python/系统架构不匹配；请安装厂商提供的 wheel。"
    ) from exc


def pick_port(ports: list[str]) -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    if not ports:
        return ""
    if len(ports) == 1:
        print("use", ports[0])
        return ports[0]
    print("select port:")
    for i, name in enumerate(ports, 1):
        print(f"  {i}. {name}")
    raw = input("index or device path: ").strip()
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= len(ports):
            return ports[n - 1]
        raise SystemExit("bad index")
    return raw


def main() -> None:
    ports = list_ports_adapter()
    print("ports:", ports)
    port = pick_port(ports)
    if not port:
        raise SystemExit("no serial port, try /dev/ttyACM0 (need dialout group)")

    print("open", port)
    with HeadbandUsb(port) as dev:
        print("attention", dev.wait_attention(8))
        print("bands", dev.bands)
        print("raw_eeg", None if dev.raw_eeg is None else len(dev.raw_eeg))
        print("wear", dev.wear)
        print("battery", dev.battery)
        print("online", dev.online)
        snap = dev.snapshot()
        print("state", getattr(snap, "wear", getattr(snap, "state", getattr(snap, "status", "unknown"))))
        print("calib_progress", getattr(snap, "calib_progress", getattr(snap, "baseline_progress", None)))
        print("mac own", snap.own_mac, "peer", snap.peer_mac)


if __name__ == "__main__":
    main()

# Linux aarch64：连续读取专注度，每 0.5 秒输出一行，便于终端查看。
# Ctrl+C 结束。
#
#   python read_stream.py
#   python read_stream.py /dev/ttyACM0

import sys
import time

from EEG import _read_attention, _snapshot_state, _normalize_progress


def pick_port(ports: list[str]) -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    if not ports:
        return ""
    if len(ports) == 1:
        print("使用设备:", ports[0])
        return ports[0]
    print("请选择设备:")
    for i, name in enumerate(ports, 1):
        print(f"  {i}. {name}")
    raw = input("输入编号或设备路径: ").strip()
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= len(ports):
            return ports[n - 1]
        raise SystemExit("设备编号无效")
    return raw


def main() -> None:
    try:
        from attention_usb import HeadbandUsb, list_ports_adapter
    except ImportError:
        raise SystemExit("未安装 attention_usb 驱动。请在设备支持的 Linux aarch64 / Python 3.11 环境中安装厂商提供的 wheel。")

    ports = list_ports_adapter() if len(sys.argv) <= 1 else []
    port = pick_port(ports)
    if not port:
        raise SystemExit("未发现头环。检查 USB 连接，或指定路径：python read_stream.py /dev/ttyACM0")

    print(f"正在连接 {port}，按 Ctrl+C 退出。", flush=True)
    last_token = None
    last_frame_at = None
    try:
        with HeadbandUsb(port) as dev:
            while True:
                snap = dev.snapshot()
                now = time.monotonic()
                token = (snap.updated_at, snap.seq)
                if snap.updated_at > 0 and token != last_token:
                    last_token = token
                    last_frame_at = now
                # The new SDK publishes lifecycle as Snapshot.wear
                # (off/baseline/normal), while older firmware used state/status.
                raw_state = getattr(snap, "wear", None)
                if raw_state in (None, "unknown"):
                    raw_state = getattr(snap, "state", getattr(snap, "status", None))
                state = _snapshot_state(snap, dev)
                attention = _read_attention(snap)
                if last_frame_at is None:
                    reading = f"状态: {state} | 专注度: -- | 等待设备数据"
                elif now - last_frame_at > 1.5:
                    reading = f"状态: {state} | 专注度: -- | 已 {now - last_frame_at:.1f} 秒未收到新帧"
                elif state in ("off", "offline"):
                    reading = "状态: off | 专注度: -- | 请佩戴头环"
                elif state == "baseline":
                    progress = _normalize_progress(getattr(
                        snap, "baseline_progress",
                        getattr(snap, "calib_progress", getattr(snap, "calibration_progress", None)),
                    ))
                    suffix = f" {progress * 100:.0f}%" if progress is not None else ""
                    reading = f"状态: baseline{suffix} | 专注度: -- | 设备正在采集基线"
                elif attention is None:
                    reading = f"状态: {state} | 专注度: -- | 等待 Attention"
                else:
                    reading = f"状态: normal | 专注度: {attention}"
                print(
                    f"[{time.strftime('%H:%M:%S')}] {port} | {reading} | 原始状态: {raw_state} | "
                    f"佩戴原值: {snap.wear} | 电量原值: {snap.battery_soc}",
                    flush=True,
                )
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n已停止读取。")
    except Exception as exc:
        raise SystemExit(f"设备读取失败: {exc}")


if __name__ == "__main__":
    main()

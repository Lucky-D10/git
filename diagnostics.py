"""Read-only headband diagnostics; never initialize GPIO."""
import time
from settings import ACTIVE


def run(port=None, stream=False):
    try:
        from attention_usb import HeadbandUsb, list_ports_adapter
    except (ImportError, OSError, RuntimeError) as exc:
        print(f"[hardware] attention_usb 加载失败: {exc}；请安装匹配系统架构和 Python 的厂商 wheel")
        return 1
    from EEG import _read_attention, _snapshot_state, _normalize_progress
    try:
        ports = [port] if port else list(ACTIVE.headband_ports or list_ports_adapter())
        if not ports:
            raise RuntimeError("未发现头环；检查 USB、串口权限，或通过 --port 指定路径")
        if len(ports) > 1:
            raise RuntimeError(f"发现多个设备 {ports}；请使用 --port 明确选择")
        with HeadbandUsb(ports[0]) as dev:
            started = time.monotonic()
            last_token, last_frame = None, None
            while True:
                now = time.monotonic()
                snap = dev.snapshot()
                token = (getattr(snap, "updated_at", None), getattr(snap, "seq", None))
                if any(token) and token != last_token:
                    last_token, last_frame = token, now
                fresh = last_frame is not None and now - last_frame <= ACTIVE.data_timeout
                state = _snapshot_state(snap, dev)
                attention = _read_attention(snap) if fresh and state == "normal" else None
                print(f"[hardware] {ports[0]} state={state} attention={attention} fresh={fresh} "
                      f"calibration={_normalize_progress(getattr(snap, 'calib_progress', None))}", flush=True)
                if not stream and attention is not None:
                    return 0
                if not stream and now - started >= ACTIVE.diagnostic_timeout:
                    raise RuntimeError("等待有效 Attention 超时；检查连接、佩戴和校准进度")
                time.sleep(ACTIVE.diagnostic_interval)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"[hardware] 设备诊断失败: {exc}")
        return 1

"""Single launcher: python app.py --help."""
import argparse
import importlib.metadata
import importlib.util
import json
import logging
from logging.handlers import RotatingFileHandler
import platform
import sys
from pathlib import Path

import settings


def environment():
    packages = {}
    for name in ("attention_usb", "RPi.GPIO", "fastapi", "uvicorn", "websockets"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    os_release = Path("/etc/os-release")
    return {"python": platform.python_version(), "platform": platform.platform(),
            "architecture": platform.machine(), "packages": packages,
            "sqlite": __import__("sqlite3").sqlite_version,
            "os_release": os_release.read_text() if os_release.exists() else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="脑电训练、双人竞速、Web 页面、设备诊断和固定回放")
    parser.add_argument("command", choices=("training", "racing", "web", "diagnose", "replay"))
    parser.add_argument("--mode", choices=("hardware", "simulation"), required=True,
                        help="必须明确选择数据来源；缺少依赖不会自动模拟")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--players", type=int, choices=(1, 2))
    parser.add_argument("--session-kind", choices=("experience", "formal"))
    parser.add_argument("--port", help="单设备诊断串口")
    parser.add_argument("--stream", action="store_true", help="连续设备诊断")
    parser.add_argument("--environment", action="store_true", help="只输出环境及配置，不打开设备")
    parser.add_argument("--output", type=Path, help="环境或回放 JSON 输出路径")
    parser.add_argument("--session-id", help="回放数据库中的指定会话")
    parser.add_argument("--database", type=Path, help="回放读取的 SQLite 文件")
    parser.add_argument("--host", default="127.0.0.1", help="Web 监听地址，默认仅本机")
    parser.add_argument("--web-port", type=int, default=8000, help="Web 监听端口")
    args = parser.parse_args(argv)
    if args.command == "training" and args.players is None:
        parser.error("训练开始前必须使用 --players 1 或 --players 2 选择人数")
    if args.command == "racing" and args.players not in (None, 2):
        parser.error("竞速要求两名玩家")
    if args.command == "web" and args.host not in ("127.0.0.1", "localhost"):
        parser.error("第一版仅允许本机访问；局域网认证与部署另行配置")
    if not 1 <= args.web_port <= 65535:
        parser.error("Web 端口必须为 1..65535")
    if args.command == "replay" and args.mode != "simulation":
        parser.error("固定回放需要 --mode simulation")
    if args.command == "diagnose" and args.mode != "hardware":
        parser.error("设备诊断需要 --mode hardware")
    config_path = args.config or settings.ROOT / "config" / (args.mode + ".json")
    try:
        config = settings.load(config_path, players=2 if args.command == "web" else args.players,
                               session_kind=args.session_kind)
        if config.mode != args.mode:
            raise ValueError("--mode 与配置文件 mode 不一致")
        if args.command == "racing" and config.players != 2:
            raise ValueError("竞速配置必须有两名玩家")
        settings.configure(config)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO,
                        format=f"%(asctime)s [{config.mode}] %(levelname)s %(message)s")
    if args.command in ("web", "training", "racing"):
        from ai.configuration import load_local_env
        from ai.provider import ProviderConfig
        try:
            load_local_env()
            ai_config = ProviderConfig.from_env()
            logging.info("AI reports: enabled=%s provider=%s model=%s simulation_allowed=%s",
                         ai_config.enabled, ai_config.provider, ai_config.model, ai_config.allow_simulation)
        except (OSError, ValueError):
            logging.warning("Local AI configuration could not be loaded; check .env.deepseek permissions and fields")
    if args.environment:
        result = {"environment": environment(), "config": config.snapshot(), "config_sha256": config.digest}
        text = json.dumps(result, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        return 0
    if args.command == "replay":
        if args.session_id:
            from backend.replay import replay_session
            result = replay_session(args.database or config.storage_path, args.session_id)
        else:
            from replay import run_all
            result = run_all()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    if args.command == "diagnose":
        from diagnostics import run
        return run(args.port, args.stream)
    if args.command == "web":
        try:
            import uvicorn
            from web.app import create_app
        except ImportError as exc:
            logging.error("Web 依赖缺失，请用项目虚拟环境执行 pip install -r requirements.txt: %s", exc)
            return 1
    import EEG
    from backend.service import BackendService
    from backend.hardware import MotorOutput
    root = None
    backend = None
    log_handler = None
    try:
        log_dir = Path(config.storage_path).resolve().parent
        log_dir.mkdir(parents=True, exist_ok=True)
        log_handler = RotatingFileHandler(log_dir / "focus.log", maxBytes=config.log_max_bytes,
                                         backupCount=config.log_backup_count, encoding="utf-8")
        log_handler.setFormatter(logging.Formatter(f"%(asctime)s [{config.mode}] %(levelname)s %(message)s"))
        logging.getLogger().addHandler(log_handler)
        from web.runtime import OperatorLease
        operator = OperatorLease(config.operator_timeout) if args.command == "web" else None
        activity = "training" if args.command == "web" else args.command
        backend = BackendService(config, activity=activity, output=MotorOutput(EEG, config),
                                 environment=environment(), operator=operator)
        EEG.attach_frame_sink(backend.submit_frame)
        EEG.start()
        backend.start()
        if args.command == "web":
            uvicorn.run(create_app(backend, operator, args.web_port), host=args.host, port=args.web_port,
                        log_level="info", access_log=False, ws_max_size=8192, ws_max_queue=16)
            return 0
        import tkinter as tk
        filename, class_name = (("Focus Training.py", "CarAttentionMonitor") if args.command == "training"
                                else ("Focus Racing.py", "FocusRacingGame"))
        spec = importlib.util.spec_from_file_location("focus_ui", settings.ROOT / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = tk.Tk()
        ui = getattr(module, class_name)(root, backend=backend)
        root.title(root.title() + f" · {config.players}人 · " + ("正式比赛" if config.session_kind == "formal" else "体验"))
        def callback_error(exc_type, value, traceback):
            EEG.emergency_stop()
            logging.exception("界面异常，轨道已停", exc_info=(exc_type, value, traceback))
            ui.emergency_stop()
        root.report_callback_exception = callback_error
        root.mainloop()
        return 0
    except Exception as exc:
        logging.error("启动失败 [%s]: %s", config.mode, exc)
        return 1
    finally:
        EEG.emergency_stop()
        if backend is not None:
            backend.stop("application_exit")
        EEG.cleanup()
        EEG.attach_frame_sink(None)
        if log_handler is not None:
            logging.getLogger().removeHandler(log_handler)
            log_handler.close()


if __name__ == "__main__":
    raise SystemExit(main())

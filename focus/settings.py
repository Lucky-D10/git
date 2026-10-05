"""Validated, immutable startup configuration. No device imports or I/O on import."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    mode: str = "hardware"
    players: int = 2
    session_kind: str = "experience"
    headband_ports: tuple = ()
    pwm_pins: tuple = (2, 11)
    direction_pins: tuple = (4, 3, 10, 9)
    standby_pin: int = 17
    pwm_frequency: int = 10000
    min_running_duty: float = 25.0
    max_running_duty: float = 50.0
    duty_rise_per_second: float = 25.0
    data_timeout: float = 1.5
    command_timeout: float = 0.8
    control_interval_ms: int = 50
    motor_interval: float = 0.02
    snapshot_interval: float = 0.01
    reconnect_interval: float = 1.0
    calibration_timeout: float = 60.0
    diagnostic_timeout: float = 8.0
    diagnostic_interval: float = 0.5
    max_race_speed: float = 10.0
    start_threshold: float = 20.0
    high_focus_threshold: float = 70.0
    reward_seconds: float = 5.0
    smoothing_seconds: float = 0.8
    virtual_distance_scale: float = 0.6
    simulation_seed: int = 20260926
    simulation_interval: float = 1.0
    simulation_calibration_seconds: float = 5.0
    countdown_seconds: float = 3.0
    zero_is_valid: bool = False
    storage_path: str = "data/focus.sqlite3"
    storage_flush_seconds: float = 0.25
    storage_max_lag_seconds: float = 2.0
    storage_queue_size: int = 256
    disk_warning_mb: float = 256.0
    log_max_bytes: int = 2097152
    log_backup_count: int = 5
    operator_timeout: float = 2.0
    web_push_interval: float = 0.1

    def __post_init__(self):
        if self.mode not in ("hardware", "simulation"):
            raise ValueError("mode 必须为 hardware 或 simulation")
        if type(self.players) is not int or self.players not in (1, 2):
            raise ValueError("players 必须为 1 或 2")
        if self.session_kind not in ("experience", "formal"):
            raise ValueError("session_kind 必须为 experience 或 formal")
        for name in ("headband_ports", "pwm_pins", "direction_pins"):
            value = getattr(self, name)
            if not isinstance(value, (tuple, list)):
                raise ValueError(f"{name} 必须为数组")
            object.__setattr__(self, name, tuple(value))
        ports = self.headband_ports
        if len(ports) > 2 or any(not isinstance(p, str) or not p.strip() for p in ports) or len(set(ports)) != len(ports):
            raise ValueError("headband_ports 必须为最多两个不重复的设备路径")
        if ports and len(ports) < self.players:
            raise ValueError("显式端口数量少于参与玩家数")
        pins = (*self.pwm_pins, *self.direction_pins, self.standby_pin)
        if len(self.pwm_pins) != 2 or len(self.direction_pins) != 4 or any(type(p) is not int or not 0 <= p <= 27 for p in pins) or len(set(pins)) != 7:
            raise ValueError("需要七个不重复的 BCM 引脚（0..27）")
        nonnumeric = {"mode", "players", "session_kind", "headband_ports", "pwm_pins", "direction_pins", "standby_pin", "simulation_seed", "zero_is_valid", "storage_path"}
        for name, value in asdict(self).items():
            if name not in nonnumeric and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} 必须是有限正数")
        if not 0 < self.min_running_duty <= self.max_running_duty <= 100:
            raise ValueError("占空比必须满足 0 < min <= max <= 100")
        if not 0 < self.start_threshold < self.high_focus_threshold < 100:
            raise ValueError("专注阈值必须满足 0 < start < high < 100")
        if type(self.control_interval_ms) is not int or type(self.pwm_frequency) is not int or type(self.simulation_seed) is not int:
            raise ValueError("控制毫秒、PWM 频率和随机种子必须为整数")
        if self.control_interval_ms / 1000 >= self.command_timeout or self.motor_interval >= self.command_timeout:
            raise ValueError("控制周期必须小于命令超时")
        if type(self.zero_is_valid) is not bool or not isinstance(self.storage_path, str) or not self.storage_path.strip():
            raise ValueError("zero_is_valid 必须为布尔值，storage_path 不可为空")
        if self.storage_flush_seconds >= self.storage_max_lag_seconds:
            raise ValueError("存储批次间隔必须小于允许的缓冲窗口")
        for name in ("storage_queue_size", "log_max_bytes", "log_backup_count"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} 必须为整数")

    def snapshot(self):
        return json.loads(json.dumps(asdict(self)))

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True).encode()).hexdigest()


ACTIVE = Config()


def load(path, **overrides):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("配置必须为 JSON 对象")
    data.update({key: value for key, value in overrides.items() if value is not None})
    try:
        return Config(**data)
    except TypeError as exc:
        raise ValueError(f"配置字段错误: {exc}") from exc


def configure(config):
    global ACTIVE
    if "EEG" in sys.modules or "focus_core" in sys.modules:
        raise RuntimeError("运行模块加载后不可更换配置；请退出并重新启动")
    ACTIVE = config

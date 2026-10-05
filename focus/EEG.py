"""USB headband acquisition and a single owner of both track outputs.

Import is inert. start() is called by an entry point; cleanup() in its finally.
Simulation is enabled only by the explicit simulation configuration selected by app.py.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import csv
from datetime import datetime
import json
import logging
import os
import math
from pathlib import Path
import random
import statistics
import tempfile
import threading
import time
from settings import ACTIVE as APP_CONFIG
import session as session_runtime
from sample_gate import SnapshotGate

# Leave empty to use attention_usb.list_ports_adapter(). Set two explicit paths
# when stable player-to-headband assignment is required.
HEADBAND_PORTS = APP_CONFIG.headband_ports
DATA_TIMEOUT = APP_CONFIG.data_timeout
COMMAND_TIMEOUT = APP_CONFIG.command_timeout
CONTROL_INTERVAL_MS = APP_CONFIG.control_interval_ms
PWM_FREQUENCY = APP_CONFIG.pwm_frequency
MIN_RUNNING_DUTY, MAX_RUNNING_DUTY = APP_CONFIG.min_running_duty, APP_CONFIG.max_running_duty
DUTY_RISE_PER_SECOND = APP_CONFIG.duty_rise_per_second
MAX_RACE_SPEED = APP_CONFIG.max_race_speed
START_THRESHOLD = APP_CONFIG.start_threshold
HIGH_FOCUS_THRESHOLD = APP_CONFIG.high_focus_threshold
REWARD_SECONDS = APP_CONFIG.reward_seconds
SMOOTHING_SECONDS = APP_CONFIG.smoothing_seconds
VIRTUAL_DISTANCE_SCALE = APP_CONFIG.virtual_distance_scale
DEVICE_STATES = ("off", "baseline", "normal")


def normalize_device_state(value):
    """Normalize vendor spellings such as ``normol`` to our three states."""
    if value is None:
        return None
    text = str(getattr(value, "value", value)).strip().lower()
    text = text.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ")
    if text in {"off", "offline", "disconnected", "not worn", "unworn", "detached", "no signal", "not connected", "unknown"}:
        return "off"
    if text in {"baseline", "calibration", "calibrating", "calibrate", "calib", "calibration in progress"}:
        return "baseline"
    if text in {"normal", "normol", "ready", "running", "online"}:
        return "normal"
    return None


def draw_device_state_machine(canvas, center_x, center_y, state, width=230, tag="device_state_machine"):
    """Draw the shared off -> baseline -> normal lifecycle on a Tk Canvas."""
    state = normalize_device_state(state) or "off"
    labels = (("off", "未佩戴"), ("baseline", "采集基线"), ("normal", "输出专注度"))
    active_index = DEVICE_STATES.index(state)
    node_width = min(68.0, width / 3.5)
    gap = (width - node_width * 3) / 2
    left = center_x - width / 2
    ids = []
    for index, (key, label) in enumerate(labels):
        x = left + index * (node_width + gap)
        node_left, node_right = x, x + node_width
        if index < active_index:
            fill, outline, text_color = "#164E3B", "#44DD88", "#B8F5D7"
        elif index == active_index:
            fill, outline, text_color = "#123B63", "#6FB8FF", "#FFFFFF"
        else:
            fill, outline, text_color = "#17212D", "#445466", "#8292A4"
        ids.append(canvas.create_rectangle(
            node_left, center_y - 14, node_right, center_y + 14,
            fill=fill, outline=outline, width=2, tags=tag,
        ))
        ids.append(canvas.create_text(
            (node_left + node_right) / 2, center_y,
            text=label, fill=text_color, font=("Microsoft YaHei", 9, "bold"), tags=tag,
        ))
        if index < len(labels) - 1:
            arrow_x1 = node_right + 3
            arrow_x2 = x + node_width + gap - 3
            ids.append(canvas.create_line(
                arrow_x1, center_y, arrow_x2, center_y,
                fill="#6C7C8E" if index >= active_index else "#44DD88",
                width=2, arrow="last", tags=tag,
            ))
    return ids


def bounded(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except (ValueError, TypeError):
        return low
    return max(low, min(high, value)) if math.isfinite(value) else low


def focus_to_power(focus, valid=True, streak=0.0):
    focus = bounded(focus)
    if not valid or focus <= START_THRESHOLD:
        return 0.0
    x = (focus - START_THRESHOLD) / (100.0 - START_THRESHOLD)
    bonus = 0.1 * x * bounded(streak / REWARD_SECONDS, 0, 1) if focus >= HIGH_FOCUS_THRESHOLD else 0.0
    return min(1.0, 0.9 * x ** 1.4 + bonus)


@dataclass(frozen=True)
class RewardState:
    attention: float = 0.0
    smoothed: float = 0.0
    power: float = 0.0
    streak: float = 0.0
    bonus: float = 0.0
    valid: bool = False


class AttentionReward:
    def __init__(self):
        self.reset()

    def reset(self):
        self.state = RewardState()
        self._since_sample = 0.0

    def update(self, attention, valid, delta_time, new_sample=True):
        raw = bounded(attention)
        dt = bounded(delta_time, 0, 0.25)
        if not valid or raw < 1:
            self.reset()
            return self.state
        self._since_sample += dt
        filtered = self.state.smoothed
        if not self.state.valid:
            filtered = raw
        elif new_sample:
            filtered += -math.expm1(-self._since_sample / SMOOTHING_SECONDS) * (raw - filtered)
        if new_sample or not self.state.valid:
            self._since_sample = 0.0
        if raw <= START_THRESHOLD:
            filtered = raw
        high = raw >= HIGH_FOCUS_THRESHOLD and filtered >= HIGH_FOCUS_THRESHOLD
        streak = min(REWARD_SECONDS, self.state.streak + dt) if high else 0.0
        power = focus_to_power(filtered, True, streak)
        self.state = RewardState(raw, filtered, power, streak, power - focus_to_power(filtered), True)
        return self.state


class TrainingMetrics:
    def __init__(self, baseline=50.0):
        self.baseline = baseline
        self.valid_seconds = self.stable_seconds = 0.0
        self.current_streak = self.best_streak = 0.0

    def update(self, attention, valid, delta_time):
        if not valid:
            self.current_streak = 0.0
            return
        dt = bounded(delta_time, 0, 0.25)
        self.valid_seconds += dt
        if attention >= self.baseline:
            self.stable_seconds += dt
            self.current_streak += dt
            self.best_streak = max(self.best_streak, self.current_streak)
        else:
            self.current_streak = 0.0

    @property
    def stable_ratio(self):
        return 100 * self.stable_seconds / self.valid_seconds if self.valid_seconds else 0.0


# Shared report helpers and Canvas visuals live here so the two UI entry points
# still use only the original three runtime files.
def summarize_series(values):
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"samples": 0, "average": 0.0, "median": 0.0, "minimum": 0.0, "maximum": 0.0}
    return {
        "samples": len(clean),
        "average": sum(clean) / len(clean),
        "median": statistics.median(clean),
        "minimum": min(clean),
        "maximum": max(clean),
    }


def build_training_report(histories, baselines, metrics, duration, mode):
    players = []
    for index, history in enumerate(histories):
        summary = summarize_series(history)
        metric = metrics[index]
        summary.update({
            "player": index + 1,
            "baseline": float(baselines[index]),
            "stable_ratio": float(metric.stable_ratio),
            "best_streak_seconds": float(metric.best_streak),
            "valid_seconds": float(metric.valid_seconds),
        })
        players.append(summary)
    report = {
        "schema_version": 1,
        "type": "focus_training",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "duration_seconds": max(0.0, float(duration)),
        "measurement_note": "读数来自 USB 头环 Attention；专注动力和进度为软件估算。",
        "players": players,
    }
    report.update(session_runtime.metadata())
    return report


def build_race_report(players, duration, virtual_distance, mode, result):
    player_rows = []
    for index, player in enumerate(players, 1):
        summary = summarize_series(player.focus_history)
        summary.update({
            "player": index,
            "color": player.color,
            "finish_time_seconds": float(player.race_time or 0.0),
            "virtual_position": float(player.position),
            "maximum_control_power_percent": float(player.max_speed * 10.0),
        })
        player_rows.append(summary)
    report = {
        "schema_version": 1,
        "type": "virtual_race",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "duration_seconds": max(0.0, float(duration)),
        "virtual_distance": float(virtual_distance),
        "result": result,
        "measurement_note": "赛程位置和用时为虚拟进度，不代表实体小车的实测位置或速度。",
        "players": player_rows,
    }
    report.update(session_runtime.metadata())
    return report


def export_session_report(report, histories, directory="reports"):
    """Write one summary JSON and one sample CSV, returning both paths."""
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    prefix = "training" if report.get("type") == "focus_training" else "race"
    json_path = output_dir / f"{prefix}-{stamp}.json"
    csv_path = output_dir / f"{prefix}-{stamp}.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    max_length = max((len(history) for history in histories), default=0)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_index", *[f"player_{index + 1}_attention" for index in range(len(histories))]])
        for sample_index in range(max_length):
            writer.writerow([
                sample_index + 1,
                *[history[sample_index] if sample_index < len(history) else "" for history in histories],
            ])
    return json_path, csv_path


def _scale_points(points, x, y, scale):
    result = []
    for px, py in points:
        result.extend((x + px * scale, y + py * scale))
    return result


def draw_race_car(canvas, x, y, color, scale=1.0, tag="race_car", state="running"):
    """Draw a compact, right-facing top-down race car and return item ids."""
    ids = []
    tags = (tag, "car_visual")
    outline = "#FFB347" if state == "warning" else "#76E6FF"
    shadow = _scale_points(((-31, -12), (20, -12), (35, 0), (20, 12), (-31, 12)), x + 3, y + 4, scale)
    body = _scale_points(((-34, -12), (18, -12), (36, 0), (18, 12), (-34, 12), (-28, 0)), x, y, scale)
    cockpit = _scale_points(((-10, -9), (13, -7), (22, 0), (13, 7), (-10, 9), (-16, 0)), x, y, scale)

    ids.append(canvas.create_polygon(*shadow, fill="#05070B", outline="", tags=tags))
    for wx in (-20, 18):
        for wy in (-14, 14):
            ids.append(canvas.create_rectangle(
                x + (wx - 7) * scale, y + (wy - 3) * scale,
                x + (wx + 7) * scale, y + (wy + 3) * scale,
                fill="#080A0E", outline="#465166", width=max(1, int(scale)), tags=tags,
            ))
    ids.append(canvas.create_polygon(*body, fill=color, outline=outline, width=max(1, int(2 * scale)), tags=tags))
    ids.append(canvas.create_polygon(*cockpit, fill="#10243D", outline="#BCEEFF", width=max(1, int(scale)), tags=tags))
    ids.append(canvas.create_line(x - 27 * scale, y, x + 28 * scale, y,
                                  fill="#EAF9FF", width=max(1, int(scale)), tags=tags))
    ids.append(canvas.create_rectangle(
        x - 38 * scale, y - 16 * scale, x - 29 * scale, y + 16 * scale,
        fill=color, outline=outline, width=max(1, int(scale)), tags=tags,
    ))
    ids.append(canvas.create_oval(x + 29 * scale, y - 7 * scale, x + 36 * scale, y - 1 * scale,
                                  fill="#FFF2A6", outline="", tags=tags))
    ids.append(canvas.create_oval(x + 29 * scale, y + 1 * scale, x + 36 * scale, y + 7 * scale,
                                  fill="#FFF2A6", outline="", tags=tags))
    if state in ("paused", "warning", "finished"):
        badge_color = {"paused": "#FFCC66", "warning": "#FF6677", "finished": "#44DD88"}[state]
        ids.append(canvas.create_oval(x - 7 * scale, y - 7 * scale, x + 7 * scale, y + 7 * scale,
                                      fill=badge_color, outline="#FFFFFF", width=1, tags=tags))
    return ids


def draw_checkered_finish(canvas, x, top, bottom, width=18, cell=9, tag="finish_line"):
    """Draw a clear checkerboard finish band."""
    ids = []
    left = x - width / 2
    rows = max(1, int((bottom - top) / cell))
    cols = max(2, int(width / cell))
    for row in range(rows + 1):
        y1 = top + row * cell
        y2 = min(bottom, y1 + cell)
        if y1 >= bottom:
            break
        for col in range(cols):
            x1 = left + col * width / cols
            x2 = left + (col + 1) * width / cols
            fill = "#F5F7FA" if (row + col) % 2 == 0 else "#111827"
            ids.append(canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline="", tags=tag))
    ids.append(canvas.create_rectangle(left, top, left + width, bottom, fill="", outline="#F5F7FA", width=1, tags=tag))
    return ids


def draw_two_lane_track(canvas, left, top, right, bottom, lane_colors, tag="track"):
    """Draw a two-lane virtual track and return both lane center lines."""
    height = bottom - top
    middle = (top + bottom) / 2
    lane_centers = (top + height * 0.27, top + height * 0.73)
    canvas.create_rectangle(left, top, right, bottom, fill="#151B27", outline="#465166", width=2, tags=tag)
    canvas.create_rectangle(left, top, right, top + 5, fill="#6D7C91", outline="", tags=tag)
    canvas.create_rectangle(left, bottom - 5, right, bottom, fill="#6D7C91", outline="", tags=tag)
    canvas.create_line(left, middle, right, middle, fill="#728096", width=2, dash=(14, 10), tags=tag)
    for ratio in (0.25, 0.5, 0.75):
        x = left + (right - left) * ratio
        canvas.create_line(x, top + 8, x, bottom - 8, fill="#2D3748", width=1, dash=(3, 5), tags=tag)
        canvas.create_text(x, top + 14, text=f"{int(ratio * 100)}%", fill="#7F8CA3", font=("Consolas", 9), tags=tag)
    canvas.create_rectangle(left - 3, top, left + 5, bottom, fill="#F4D35E", outline="", tags=tag)
    canvas.create_text(left + 12, top + 12, text="起点", fill="#F4D35E", font=("Microsoft YaHei", 9, "bold"), anchor="w", tags=tag)
    draw_checkered_finish(canvas, right, top, bottom, tag=tag)
    canvas.create_text(right - 13, top + 12, text="虚拟终点", fill="#F5F7FA", font=("Microsoft YaHei", 9, "bold"), anchor="e", tags=tag)
    for index, (center, color) in enumerate(zip(lane_centers, lane_colors), 1):
        canvas.create_rectangle(left + 10, center - 14, left + 42, center + 14, fill="#0C111B", outline=color, width=1, tags=tag)
        canvas.create_text(left + 26, center, text=str(index), fill=color, font=("Consolas", 12, "bold"), tags=tag)
    return lane_centers

HeadbandUsb = list_ports_adapter = GPIO = None
_dependency_errors = {}
if APP_CONFIG.mode == "hardware":
    try:
        from attention_usb import HeadbandUsb, list_ports_adapter
    except (ImportError, OSError, RuntimeError) as exc:
        _dependency_errors["attention_usb"] = str(exc)
    try:
        import RPi.GPIO as GPIO
    except (ImportError, OSError, RuntimeError) as exc:
        _dependency_errors["RPi.GPIO"] = str(exc)

GPIO_AVAILABLE = GPIO is not None
hardware_available = GPIO_AVAILABLE and HeadbandUsb is not None
simulation_mode = APP_CONFIG.mode == "simulation"
logger = logging.getLogger("EEGSystem")
pwm_pin_1, pwm_pin_2 = APP_CONFIG.pwm_pins
AIN1, AIN2, BIN1, BIN2 = APP_CONFIG.direction_pins
STBY = APP_CONFIG.standby_pin
MOTOR_COMMAND_TIMEOUT = COMMAND_TIMEOUT


@dataclass(frozen=True)
class AttentionSample:
    attention: int | None
    received_at: float
    valid: bool
    sequence: int
    # A manually created valid sample is treated as normal for compatibility;
    # device snapshots always provide an explicit state through _snapshot_sample.
    state: str = "normal"
    baseline: float | None = None
    baseline_progress: float | None = None
    wear: object | None = None
    battery_soc: float | None = None


class DeviceStateMachine:
    """Own one headband's lifecycle and convert snapshots into safe samples."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = "off"
        self.state_since = self.clock()
        self.last_update = None
        self.last_event = "init"
        self.transition_count = 0
        self.baseline = None
        self.baseline_progress = None
        self.wear = None
        self.battery_soc = None

    def reset(self):
        self.__init__(self.clock)

    def _transition(self, state, event, now):
        if state != self.state:
            self.state = state
            self.state_since = now
            self.transition_count += 1
        self.last_event = event

    def update(self, snapshot, now=None, device=None):
        now = self.clock() if now is None else float(now)
        state = _snapshot_state(snapshot, device)
        self.last_update = now
        self.wear = _read_wear(snapshot, device)
        self.battery_soc = getattr(snapshot, "battery_soc", getattr(device, "battery_soc", None) if device else None)
        self.baseline = _read_snapshot_value(snapshot, device, ("baseline", "baseline_attention", "baseline_value"))
        self.baseline_progress = _read_snapshot_value(
            snapshot, device,
            ("baseline_progress", "calibration_progress", "baseline_percent", "calib_progress"),
        )
        self.baseline_progress = _normalize_progress(self.baseline_progress)
        attention = _read_attention(snapshot)
        # ``normal`` means that an attention value is actually available.  A
        # stale normal flag without a value is still preparation/offline data.
        if state == "normal" and attention is None:
            state = "baseline" if self.wear is True else "off"
        self._transition(state, f"snapshot:{state}", now)
        valid = self.state == "normal" and attention is not None and 1 <= attention <= 100
        return AttentionSample(
            attention, now, valid, 0, self.state,
            _to_float(self.baseline), self.baseline_progress,
            self.wear, self.battery_soc,
        )

    def tick(self, now=None):
        """Advance timeout transitions even when the SDK has stopped publishing."""
        now = self.clock() if now is None else float(now)
        if self.last_update is None or now - self.last_update <= DATA_TIMEOUT or self.state == "off":
            return None
        self._transition("off", "timeout", now)
        return AttentionSample(None, now, False, 0, "off", self._to_baseline(), self.baseline_progress, self.wear, self.battery_soc)

    def _to_baseline(self):
        return _to_float(self.baseline)


def _speed_to_duty(speed):
    speed = bounded(speed, 0, MAX_RACE_SPEED)
    return 0.0 if speed <= 0 else MIN_RUNNING_DUTY + speed / MAX_RACE_SPEED * (MAX_RUNNING_DUTY - MIN_RUNNING_DUTY)


class MotorController:
    """The policy used by the worker; each lane follows its own signal state."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.enabled = False
        self.duties = (0.0, 0.0)
        self.targets = (0.0, 0.0)
        self._last_command = None
        self.reason = "未开始"

    def enable(self, enabled=True):
        self.enabled = bool(enabled)
        self.duties = self.targets = (0.0, 0.0)
        self._last_command = self.clock() if enabled else None
        self.reason = "" if enabled else "已暂停"

    def command_speed(self, speed_1, speed_2):
        if self.enabled:
            self.targets = (_speed_to_duty(speed_1), _speed_to_duty(speed_2))
            self._last_command = self.clock()

    def update(self, delta_time=0.02, valid=(True, True)):
        valid = tuple(bool(value) for value in valid)
        if self.enabled and (self._last_command is None or self.clock() - self._last_command > COMMAND_TIMEOUT):
            self.emergency_stop("控制心跳超时")
        if not self.enabled:
            return (0.0, 0.0)
        step = DUTY_RISE_PER_SECOND * bounded(delta_time, 0, 0.1)
        self.duties = tuple(
            0.0 if not valid[index] else min(target, current + step)
            for index, (current, target) in enumerate(zip(self.duties, self.targets))
        )
        return self.duties

    def emergency_stop(self, reason="已急停"):
        self.enable(False)
        self.reason = reason


motor_lock = threading.RLock()
sample_lock = threading.RLock()
controller = MotorController()
motor_enabled = False
_samples = [AttentionSample(None, 0, False, 0) for _ in range(2)]
Attention_1 = Attention_2 = 0
AttentionValid_1 = AttentionValid_2 = False
DeviceState_1 = DeviceState_2 = "off"
LastUpdate_1 = LastUpdate_2 = 0.0
SampleSequence_1 = SampleSequence_2 = 0
gpio_initialized = False
pwm_1 = pwm_2 = None
running = False
_stop = threading.Event()
_threads = []
_process_lock = None
_gpio_fault = False
_frame_sink = None


def _publish(device_id, sample):
    with sample_lock:
        index = device_id - 1
        sample = replace(sample, sequence=_samples[index].sequence + 1)
        _samples[index] = sample
        # Displays may use globals; control always uses atomic snapshots.
        for name, value in (("Attention", sample.attention or 0), ("AttentionValid", sample.valid),
                            ("DeviceState", sample.state), ("LastUpdate", sample.received_at),
                            ("SampleSequence", sample.sequence)):
            globals()[f"{name}_{device_id}"] = value


def attach_frame_sink(sink):
    """Bind a non-blocking queue adapter before starting acquisition."""
    global _frame_sink
    _frame_sink = sink


def _emit_frame(lane, **frame):
    if _frame_sink is not None:
        _frame_sink({"lane": lane, **frame}, absolute=True)


def get_samples(now=None):
    now = time.monotonic() if now is None else now
    with sample_lock:
        samples = []
        for sample in _samples:
            fresh = 0 <= now - sample.received_at <= DATA_TIMEOUT
            samples.append(replace(sample, valid=sample.valid and fresh, state=sample.state if fresh else "off"))
        return tuple(samples)


def device_has_recent_data(device_id, max_age=DATA_TIMEOUT):
    sample = get_samples()[device_id - 1]
    return sample.valid and time.monotonic() - sample.received_at <= min(max_age, DATA_TIMEOUT)


def device_state(device_id):
    return get_samples()[device_id - 1].state


def device_feedback(device_id):
    """Return the single UI contract for the three device states."""
    sample = get_samples()[device_id - 1]
    state = normalize_device_state(sample.state) or "off"
    if state == "baseline":
        progress = sample.baseline_progress
        progress_text = f"（{progress * 100:.0f}%）" if progress is not None else ""
        return {
            "state": "baseline",
            "title": f"基线采集中{progress_text}",
            "detail": "请保持佩戴并自然坐好，等待基线采集完成",
            "color": "#6FB8FF",
            "attention": None,
            "ready": False,
        }
    if state == "normal" and sample.valid and sample.attention is not None:
        return {
            "state": "normal",
            "title": f"正常输出 · 专注度 {sample.attention}",
            "detail": "设备状态正常，可以开始",
            "color": "#44DD88",
            "attention": sample.attention,
            "ready": True,
        }
    return {
        "state": "off",
        "title": "未佩戴",
        "detail": "请佩戴头环；若已佩戴，请检查 USB 连接和电极接触",
        "color": "#FFB347",
        "attention": None,
        "ready": False,
    }


def _ensure_gpio():
    global gpio_initialized, pwm_1, pwm_2
    if simulation_mode or gpio_initialized:
        return
    if GPIO is None:
        raise RuntimeError("缺少 RPi.GPIO；请在树莓派上安装依赖")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(STBY, GPIO.OUT, initial=GPIO.LOW)
    for pin in (pwm_pin_1, pwm_pin_2, AIN1, AIN2, BIN1, BIN2):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    pwm_1 = GPIO.PWM(pwm_pin_1, PWM_FREQUENCY)
    pwm_2 = GPIO.PWM(pwm_pin_2, PWM_FREQUENCY)
    pwm_1.start(0)
    pwm_2.start(0)
    gpio_initialized = True


def _write_outputs(duty_1, duty_2):
    """Only called with motor_lock held; never initializes GPIO implicitly."""
    global _gpio_fault, motor_enabled
    if simulation_mode or not gpio_initialized:
        return
    try:
        if duty_1 <= 0 and duty_2 <= 0:
            GPIO.output(STBY, GPIO.LOW)
        GPIO.output(AIN1, GPIO.HIGH)
        GPIO.output(AIN2, GPIO.LOW)
        GPIO.output(BIN1, GPIO.LOW)
        GPIO.output(BIN2, GPIO.HIGH)
        pwm_1.ChangeDutyCycle(bounded(duty_1, 0, MAX_RUNNING_DUTY))
        pwm_2.ChangeDutyCycle(bounded(duty_2, 0, MAX_RUNNING_DUTY))
        if duty_1 > 0 or duty_2 > 0:
            GPIO.output(STBY, GPIO.HIGH)
    except Exception:
        _gpio_fault = True
        motor_enabled = False
        controller.emergency_stop("GPIO 输出故障，请退出检查")
        logger.exception("PWM控制失败")
        try:
            GPIO.output(STBY, GPIO.LOW)
        except Exception:
            logger.exception("无法拉低 STBY")


def enable_motors(enabled=True, mode=None):
    global motor_enabled
    with motor_lock:
        if enabled and (not running or _gpio_fault):
            controller.emergency_stop("设备未就绪")
            motor_enabled = False
            _write_outputs(0, 0)
            return False
        controller.enable(enabled)
        motor_enabled = controller.enabled
        _write_outputs(0, 0)
        return motor_enabled


def set_race_speeds(speed_1, speed_2):
    with motor_lock:
        controller.command_speed(speed_1, speed_2)


def emergency_stop():
    global motor_enabled
    with motor_lock:
        controller.emergency_stop()
        motor_enabled = False
        _write_outputs(0, 0)


def motor_status():
    with motor_lock:
        return controller.enabled, controller.reason, controller.duties


def _headband_ports():
    """Return the currently visible ports, preserving explicit assignment."""
    if HEADBAND_PORTS:
        return tuple(HEADBAND_PORTS)
    if list_ports_adapter is None:
        return ()
    try:
        return tuple(dict.fromkeys(str(port) for port in list_ports_adapter()))
    except Exception as exc:
        logger.warning("无法发现头环: %s", exc)
        return ()


def _to_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_progress(value):
    value = _to_float(value)
    if value is None:
        return None
    if value > 1:
        value /= 100.0
    return max(0.0, min(1.0, value))


def _read_snapshot_value(snapshot, device, names):
    for owner in (snapshot, device):
        if owner is None:
            continue
        for name in names:
            value = getattr(owner, name, None)
            if value is not None:
                return value
    return None


def _read_attention(snapshot):
    attention = getattr(snapshot, "attention", None)
    try:
        return int(round(float(attention))) if attention is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _snapshot_state(snapshot, device=None):
    """Read the vendor state and fall back safely when SDK versions differ."""
    wear = _read_wear(snapshot, device)
    online = _read_online(snapshot, device)
    lead_off = _read_snapshot_value(snapshot, device, ("lead_off", "electrode_off"))
    baseline_progress = _normalize_progress(_read_snapshot_value(
        snapshot, device, ("baseline_progress", "calibration_progress", "baseline_percent", "calib_progress")
    ))
    baseline_flag = _read_snapshot_value(
        snapshot, device, (
            "calibrating", "is_calibrating", "calibration", "baseline_active", "is_baseline",
        )
    )
    calibrated = _read_snapshot_value(snapshot, device, ("calibrated",))
    # An explicit contact/connection loss always wins over a stale state field.
    # Some SDK versions keep the previous ``normal`` value after the band is
    # removed, so checking this before the vendor state is essential.
    if lead_off is True or wear is False or online is False:
        return "off"
    # The new attention_usb SDK exposes the lifecycle directly as
    # Snapshot.wear: ``off``, ``baseline`` or ``normal``.  Prefer it over
    # inferred values so a temporary Attention value during calibration cannot
    # make the UI or motor controller report normal output.
    if wear == "baseline":
        return "baseline"
    if wear == "normal":
        if baseline_progress is not None and baseline_progress < 1.0:
            return "baseline"
        if calibrated is False:
            return "baseline"
        return "normal"
    explicit_state = None
    for owner in (snapshot, device):
        if owner is None:
            continue
        for name in ("state", "status", "device_state", "mode", "phase"):
            explicit_state = normalize_device_state(getattr(owner, name, None))
            if explicit_state is not None:
                break
        if explicit_state is not None:
            break
    if explicit_state == "off":
        return "off"
    # During calibration some firmware already exposes a temporary Attention
    # value. Progress/active flags must keep that frame in baseline.
    if baseline_progress is not None and baseline_progress < 1.0:
        return "baseline"
    if isinstance(baseline_flag, str):
        baseline_flag = baseline_flag.strip().lower() in {"1", "true", "yes", "on", "active", "running", "calibrating"}
    # ``calibrated=False`` is the SDK's boolean form of baseline collection.
    if calibrated is False and wear is not False:
        return "baseline"
    if baseline_flag is True:
        return "baseline"
    if explicit_state is not None:
        return explicit_state
    if wear is True and getattr(snapshot, "attention", None) is None:
        return "baseline"
    if getattr(snapshot, "attention", None) is not None:
        return "normal"
    return "off"


def _read_wear(snapshot, device=None):
    """Read the vendor's wear/contact flag across SDK naming variants."""
    value = _read_snapshot_value(snapshot, device, ("wear", "worn", "is_worn", "on_head", "contact"))
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower().replace("_", " ").replace("-", " ")
        if text in {"true", "1", "yes", "on", "worn", "wear", "佩戴", "已佩戴"}:
            return True
        if text in {"false", "0", "no", "off", "unworn", "not worn", "未佩戴"}:
            return False
        if text in {"baseline", "calibration", "calibrating", "calib", "calibration in progress"}:
            return "baseline"
        if text in {"normal", "ready", "running", "output"}:
            return "normal"
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return None


def _read_online(snapshot, device=None):
    value = _read_snapshot_value(snapshot, device, ("online", "connected", "is_connected"))
    if value is None:
        return None
    if isinstance(value, dict):
        # attention_usb exposes ``online`` as {adapter, headband_ble}; both
        # links must be present before a snapshot is considered connected.
        adapter = value.get("adapter")
        headband = value.get("headband_ble")
        known = [item for item in (adapter, headband) if item is not None]
        if not known:
            return None
        return all(bool(item) for item in known)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on", "online", "connected"}:
            return True
        if text in {"false", "0", "no", "off", "offline", "disconnected"}:
            return False
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return None


def _snapshot_sample(snapshot, now, device=None, state_machine=None):
    """Convert a vendor snapshot; only normal state can drive a lane."""
    machine = state_machine or DeviceStateMachine()
    return machine.update(snapshot, now, device)


def _check_headband_connection(port, snapshot=None, device=None):
    """Check transport independently of cached sample identity.

    Linux removes the tty node (or breaks its by-id symlink) on USB removal.
    SDK snapshots may remain cached indefinitely after that removal.
    """
    if str(port).startswith("/dev/") and not os.path.exists(port):
        raise ConnectionError(f"USB serial port disappeared: {port}")
    # A cached snapshot must not mask a newer disconnect flag on the device.
    if _read_online(snapshot) is False or _read_online(None, device) is False:
        raise ConnectionError(f"Headband link disconnected: {port}")


def _headband_worker(device_id):
    generation = 0
    while not _stop.is_set():
        ports = _headband_ports()
        port = ports[device_id - 1] if len(ports) >= device_id else None
        if not port:
            _publish(device_id, AttentionSample(None, time.monotonic(), False, 0, "off"))
            _emit_frame(device_id, kind="status", received=time.monotonic(), connected=False,
                        worn=None, state="off", reason="not_connected")
            _stop.wait(APP_CONFIG.reconnect_interval)
            continue
        try:
            _check_headband_connection(port)
            with HeadbandUsb(port) as device:
                logger.info("头环%d串口已打开: %s", device_id, port)
                generation += 1
                state_machine = DeviceStateMachine()
                gate = SnapshotGate()
                ordinal = 0
                link_seen = False
                while not _stop.is_set():
                    _check_headband_connection(port)
                    now = time.monotonic()
                    snapshot = device.snapshot()
                    if not link_seen and (_read_online(snapshot) is False or _read_online(None, device) is False):
                        # Opening the adapter may precede its BLE handshake.
                        # Do not repeatedly close it before it can connect.
                        _check_headband_connection(port)
                        _publish(device_id, AttentionSample(None, now, False, 0, "off"))
                        _emit_frame(device_id, kind="status", received=now, connected=False,
                                    worn=None, state="off", reason="not_connected")
                        _stop.wait(APP_CONFIG.snapshot_interval)
                        continue
                    _check_headband_connection(port, snapshot, device)
                    link_seen = True
                    resolved_state = _snapshot_state(snapshot, device)
                    should_publish = gate.accept(snapshot, resolved_state)
                    if should_publish:
                        previous_state = state_machine.state
                        sample = _snapshot_sample(snapshot, now, device, state_machine)
                        connected = _read_online(snapshot, device)
                        worn = _read_wear(snapshot, device)
                        worn = True if worn in ("baseline", "normal") else worn
                        if gate.new_sample:
                            ordinal += 1
                            _emit_frame(device_id, raw=getattr(snapshot, "attention", None), sequence=ordinal,
                                        vendor_sequence=getattr(snapshot, "seq", None), vendor_updated_at=getattr(snapshot, "updated_at", None),
                                        received=now, generation=generation, connected=connected is not False,
                                        worn=worn, state=resolved_state, device=port,
                                        device_baseline=sample.baseline, calibration_progress=sample.baseline_progress)
                        else:
                            sample = replace(sample, valid=False)
                            _emit_frame(device_id, kind="status", received=now, connected=connected is not False, worn=worn,
                                        device_baseline=sample.baseline, calibration_progress=sample.baseline_progress,
                                        state=resolved_state, reason="unverified_identity" if gate.reason == "unverified_identity" else "not_worn" if worn is False else "awaiting_new_frame")
                        _publish(device_id, sample)
                        if sample.state != previous_state:
                            logger.info("头环%d状态: %s -> %s", device_id, previous_state, sample.state)
                    timeout_sample = state_machine.tick(now)
                    if timeout_sample is not None:
                        _publish(device_id, timeout_sample)
                    _stop.wait(APP_CONFIG.snapshot_interval)
        except Exception as exc:
            _publish(device_id, AttentionSample(None, time.monotonic(), False, 0, "off"))
            _emit_frame(device_id, kind="status", received=time.monotonic(), connected=False,
                        worn=None, state="off", reason="connection_error")
            logger.warning("头环%d连接失败，将重试: %s", device_id, exc)
        _stop.wait(APP_CONFIG.reconnect_interval)


def _simulate():
    values = [50, 50]
    started = time.monotonic()
    rng = random.Random(APP_CONFIG.simulation_seed)
    sequence = 0
    while not _stop.is_set():
        sequence += 1
        elapsed = time.monotonic() - started
        state = "baseline" if elapsed < APP_CONFIG.simulation_calibration_seconds else "normal"
        progress = min(1.0, elapsed / APP_CONFIG.simulation_calibration_seconds)
        for index in range(2):
            if index >= APP_CONFIG.players:
                _publish(index + 1, AttentionSample(None, time.monotonic(), False, 0, "off"))
                continue
            if state == "normal":
                values[index] = int(bounded(values[index] + rng.randint(-12, 12), 1, 100))
                sample = AttentionSample(values[index], time.monotonic(), True, 0, state, 50.0, 1.0)
            else:
                sample = AttentionSample(None, time.monotonic(), False, 0, state, 50.0, progress)
            _publish(index + 1, sample)
            _emit_frame(index + 1, raw=sample.attention, received=sample.received_at, sequence=sequence,
                        generation=0, connected=True, worn=True, state=state, device="simulation",
                        calibration_progress=progress, device_baseline=50.0)
        _stop.wait(APP_CONFIG.simulation_interval)


_control_bindings = (1, 2)


def _motor_tick(now, delta_time):
    """Atomic decision + write, shared by the worker and integration tests."""
    global motor_enabled
    with motor_lock:
        samples = get_samples(now)
        valid = tuple(samples[index - 1].valid for index in _control_bindings)
        duties = controller.update(delta_time, (valid + (False, False))[:2])
        motor_enabled = controller.enabled
        _write_outputs(*duties)
        return duties


def f2():
    global _gpio_fault
    previous = time.monotonic()
    try:
        while not _stop.is_set():
            now = time.monotonic()
            _motor_tick(now, now - previous)
            previous = now
            _stop.wait(APP_CONFIG.motor_interval)
    except Exception:
        _gpio_fault = True
        logger.exception("控制线程异常退出")
    finally:
        emergency_stop()


def start(with_control=True):
    global running, _process_lock, _gpio_fault
    if running:
        return
    if not simulation_mode and not hardware_available:
        missing = []
        if HeadbandUsb is None:
            missing.append("attention_usb（厂商头环 SDK）: " + _dependency_errors.get("attention_usb", "未安装"))
        if GPIO is None:
            missing.append("RPi.GPIO（树莓派 GPIO）: " + _dependency_errors.get("RPi.GPIO", "未安装"))
        raise RuntimeError("实机模式无法启动，缺少：" + "、".join(missing) + "。请安装后重试；如只想演示，请明确使用 app.py ... --mode simulation")
    if any(thread.is_alive() for thread in _threads):
        raise RuntimeError("上一次采集线程尚未退出，请退出程序后重试")
    if not simulation_mode and len(HEADBAND_PORTS) >= 2 and HEADBAND_PORTS[0] == HEADBAND_PORTS[1]:
        raise ValueError("两个头环不能配置成同一设备")
    try:
        if not simulation_mode and os.name == "posix":
            import fcntl
            _process_lock = open(os.path.join(tempfile.gettempdir(), "focus-race-gpio.lock"), "a")
            try:
                fcntl.flock(_process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _process_lock.close()
                _process_lock = None
                raise RuntimeError("另一个界面正在使用轨道，请先关闭它")
        _ensure_gpio()
        _gpio_fault = False
        _stop.clear()
        running = True
        for device_id in (1, 2):
            _publish(device_id, AttentionSample(None, 0, False, 0))
        jobs = [(_simulate, ())] if simulation_mode else [(_headband_worker, (1,)), (_headband_worker, (2,))]
        if with_control:
            jobs.append((f2, ()))
        for target, args in jobs:
            thread = threading.Thread(target=target, args=args, daemon=True)
            _threads.append(thread)
            thread.start()
        logger.info("运行模式: %s；配置摘要 %s", "内置模拟数据" if simulation_mode else "attention_usb 实机", APP_CONFIG.digest[:12])
    except Exception:
        cleanup()
        raise


def cleanup():
    global running, gpio_initialized, _process_lock
    _stop.set()
    running = False
    emergency_stop()
    for thread in _threads:
        if thread is not threading.current_thread():
            thread.join(timeout=1.0)
    _threads[:] = [thread for thread in _threads if thread.is_alive()]
    try:
        with motor_lock:
            if not simulation_mode and GPIO is not None and (gpio_initialized or _process_lock is not None):
                try:
                    GPIO.output(STBY, GPIO.LOW)
                    for pwm in (pwm_1, pwm_2):
                        if pwm is not None:
                            pwm.stop()
                finally:
                    GPIO.cleanup((pwm_pin_1, pwm_pin_2, AIN1, AIN2, BIN1, BIN2, STBY))
            gpio_initialized = False
    finally:
        if _process_lock is not None:
            _process_lock.close()
            _process_lock = None

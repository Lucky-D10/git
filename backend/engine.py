"""Deterministic session engine. No Tk, threads, database, or GPIO dependencies."""
from dataclasses import asdict, dataclass, field
import math

ALGORITHM_VERSION = "stage2-v1"
TERMINAL = {"finished", "aborted"}


@dataclass
class Lane:
    connected: bool = False
    worn: object = None
    calibration: str = "off"
    calibration_progress: object = None
    calibration_since: object = None
    device_baseline: object = None
    reference: float = 50.0
    raw: object = None
    smoothed: object = None
    received: float = -1e30
    sequence: object = None
    generation: int = -1
    valid: bool = False
    reason: str = "not_connected"
    streak: float = 0.0
    valid_seconds: float = 0.0
    target_seconds: float = 0.0
    current_streak: float = 0.0
    best_streak: float = 0.0
    sample_count: int = 0
    total: float = 0.0
    minimum: object = None
    maximum: object = None
    first_value: object = None
    last_value: object = None
    position: float = 0.0
    finish_time: object = None
    power: float = 0.0
    max_power: float = 0.0
    history: list = field(default_factory=list)


class Engine:
    def __init__(self, config, session_id="session", activity="training", duration=60.0,
                 distance=100.0, references=None):
        if activity not in ("training", "racing") or (activity == "racing" and config.players != 2):
            raise ValueError("竞速要求两名玩家；activity 必须为 training/racing")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (duration, distance)):
            raise ValueError("时长和距离必须为有限正数")
        references = references or [50.0] * config.players
        if len(references) != config.players or any(not math.isfinite(v) or not 0 <= v <= 100 for v in references):
            raise ValueError("个人参考值必须为 0..100 且与人数一致")
        self.config, self.session_id, self.activity = config, session_id, activity
        self.duration, self.distance = float(duration), float(distance)
        self.state, self.safety = "preparing", "inhibited"
        self.reason, self.result = "", None
        self.now = self.elapsed = 0.0
        self.countdown_end = None
        self.lanes = [Lane(reference=v) for v in references]
        self.events, self.sample_rows = [], []
        self.last_rejection = ""
        self.event("session_created", old="idle", new="preparing", reason="prepare")

    def event(self, name, **details):
        self.events.append({"t": self.now, "event": name, **details})

    def transition(self, state, reason):
        old = self.state
        self.state, self.reason = state, reason
        self.last_rejection = ""
        self.set_safety("allowed" if state == "running" else self.safety if self.safety.endswith("locked") else "inhibited", reason)
        self.event("state_transition", old=old, new=state, reason=reason)
        if state != "running":
            for lane in self.lanes:
                lane.power = lane.streak = lane.current_streak = 0.0

    def set_safety(self, safety, reason):
        if self.safety != safety:
            self.event("safety_transition", old=self.safety, new=safety, reason=reason)
            self.safety = safety

    def ready(self):
        return all(l.valid for l in self.lanes)

    def intent(self, action, session_id, **options):
        if session_id != self.session_id:
            self.last_rejection = "stale_session"
            self.event("intent_rejected", action=action, reason="stale_session")
            return False
        if action == "emergency" and self.safety != "fault_locked":
            self.set_safety("emergency_locked", "operator_emergency")
            self.transition("aborted", "emergency")
            return True
        if action == "fault":
            self.set_safety("fault_locked", options.get("reason", "fault"))
            self.transition("aborted", options.get("reason", "fault"))
            return True
        if action == "reset" and self.safety == "emergency_locked" and options.get("confirmed") is True:
            self.set_safety("inhibited", "operator_reset")
            self.event("safety_reset", reason="operator_confirmed")
            return True
        accepted = False
        if not self.safety.endswith("locked"):
            if action == "operator_lost" and self.state in ("running", "countdown"):
                self.transition("paused", "operator_heartbeat_timeout")
                return True
            if action in ("start", "resume") and self.state == ("preparing" if action == "start" else "paused") and self.ready():
                self.countdown_end = self.now + self.config.countdown_seconds
                self.transition("countdown", action)
                accepted = True
            elif action == "pause" and self.state == "running":
                self.transition("paused", "manual_pause")
                accepted = True
            elif action == "end" and self.state not in TERMINAL:
                self.transition("finished", "manual_end")
                accepted = True
        if not accepted:
            self.last_rejection = "not_ready" if not self.ready() else "illegal_state"
            self.event("intent_rejected", action=action, reason="not_ready" if not self.ready() else "illegal_state",
                       devices=[l.reason for l in self.lanes])
        else:
            self.last_rejection = ""
        return accepted

    def _invalidate(self, lane, reason):
        lane.valid = False
        lane.reason = reason
        lane.power = lane.streak = lane.current_streak = 0.0
        lane.smoothed = None

    def feed(self, lane_id, frame):
        """Frame identity is scoped by adapter connection generation, never GUI polling."""
        lane = self.lanes[lane_id - 1]
        if self.safety.endswith("locked"):
            self.event("sample_ignored", lane=lane_id, reason="safety_locked")
            return False
        if frame.get("kind") == "status":
            old = lane.reason
            lane.connected = frame.get("connected", lane.connected)
            lane.worn = frame.get("worn", lane.worn)
            lane.calibration = frame.get("state", lane.calibration)
            self._invalidate(lane, frame.get("reason", "not_connected"))
            if old != lane.reason:
                self.event("device_transition", lane=lane_id, old=old, new=lane.reason)
            self._guards()
            return False
        raw, seq = frame.get("raw"), frame.get("sequence")
        received = frame.get("received", self.now)
        generation = frame.get("generation", 0)
        reason = ""
        if not isinstance(received, (float, int)) or not math.isfinite(received) or received > self.now + 1e-7:
            reason = "invalid_timestamp"
        elif generation < lane.generation:
            reason = "old_connection"
        elif generation == lane.generation and seq is not None and lane.sequence is not None and seq <= lane.sequence:
            reason = "duplicate" if seq == lane.sequence else "out_of_order"
        elif received < lane.received:
            reason = "out_of_order"
        elif seq is None:
            reason = "unverified_identity"
        if reason in ("duplicate", "out_of_order", "old_connection", "invalid_timestamp"):
            self.event("sample_rejected", lane=lane_id, reason=reason, sequence=seq)
            return False
        previous_reason = lane.reason
        old_received = lane.received
        lane.connected = frame.get("connected", False)
        lane.worn = frame.get("worn")
        state = frame.get("state", "off")
        if state == "baseline" and lane.calibration != "baseline":
            lane.calibration_since = self.now
        lane.calibration = state
        lane.calibration_progress = frame.get("calibration_progress")
        lane.device_baseline = frame.get("device_baseline")
        lane.generation, lane.sequence = generation, seq
        lane.raw, lane.received = raw, received
        if not reason:
            if not lane.connected:
                reason = "not_connected"
            elif lane.worn is False:
                reason = "not_worn"
            elif state == "baseline":
                reason = "calibrating"
            elif state != "normal":
                reason = "not_ready"
            elif raw is None:
                reason = "missing_attention"
            elif type(raw) not in (int, float) or not math.isfinite(raw):
                reason = "nonfinite_or_nonnumeric"
            elif not 0 <= raw <= 100:
                reason = "out_of_range"
            elif raw == 0 and not self.config.zero_is_valid:
                reason = "sdk_zero_unverified"
            elif self.now >= received + self.config.data_timeout:
                reason = "stale"
        if reason:
            self._invalidate(lane, reason)
        else:
            if lane.smoothed is None or not lane.valid:
                lane.smoothed = float(raw)
            else:
                dt = max(0.0, received - old_received)
                lane.smoothed += -math.expm1(-dt / self.config.smoothing_seconds) * (raw - lane.smoothed)
            if raw <= self.config.start_threshold:
                lane.smoothed = float(raw)
            lane.valid, lane.reason = True, "valid"
            if raw < self.config.high_focus_threshold or lane.smoothed < self.config.high_focus_threshold:
                lane.streak = 0.0
            if self.state == "running":
                lane.sample_count += 1
                lane.total += raw
                lane.minimum = raw if lane.minimum is None else min(lane.minimum, raw)
                lane.maximum = raw if lane.maximum is None else max(lane.maximum, raw)
                lane.first_value = raw if lane.first_value is None else lane.first_value
                lane.last_value = raw
                lane.history.append((self.elapsed, raw))
                lane.history = lane.history[-1000:]
        self.sample_rows.append({"t": self.now, "source_t": received, "lane": lane_id,
                                 "device": frame.get("device", f"headband-{lane_id}"),
                                 "vendor_sequence": frame.get("vendor_sequence"), "vendor_updated_at": frame.get("vendor_updated_at"),
                                 "sequence": seq, "generation": generation, "raw": raw,
                                 "smoothed": lane.smoothed, "valid": lane.valid, "reason": lane.reason,
                                 "connected": lane.connected, "worn": lane.worn, "state": state,
                                 "session_state": self.state})
        if lane.reason != previous_reason:
            self.event("device_transition", lane=lane_id, old=previous_reason, new=lane.reason)
        self._guards()
        self._powers()
        return True

    def _guards(self):
        for i, lane in enumerate(self.lanes, 1):
            reason = None
            if lane.valid and self.now >= lane.received + self.config.data_timeout - 1e-9:
                reason = "stale"
            if lane.calibration == "baseline" and lane.calibration_since is not None and self.now >= lane.calibration_since + self.config.calibration_timeout:
                reason = "calibration_timeout"
            if reason and reason != lane.reason:
                old = lane.reason
                self._invalidate(lane, reason)
                self.event("device_transition", lane=i, old=old, new=reason)
        if self.state == "countdown" and not self.ready():
            self.countdown_end = None
            self.transition("paused" if self.elapsed else "preparing", "countdown_signal_lost")
        if self.state == "running" and not any(l.valid for l in self.lanes) and self.config.session_kind == "formal":
            self.transition("aborted", "all_signals_lost")

    def _base_bonus(self, lane):
        if not lane.valid or lane.raw <= self.config.start_threshold:
            return 0.0, 0.0
        x = max(0.0, (lane.smoothed - self.config.start_threshold) / (100 - self.config.start_threshold))
        return .9 * x ** 1.4, .1 * x if lane.raw >= self.config.high_focus_threshold and lane.smoothed >= self.config.high_focus_threshold else 0.0

    def _integral(self, lane, dt):
        base, bonus = self._base_bonus(lane)
        r, s = self.config.reward_seconds, lane.streak
        ramp = min(dt, max(0.0, r - s))
        return base * dt + bonus * ((s * ramp + ramp * ramp / 2) / r + dt - ramp)

    def _powers(self):
        for lane in self.lanes:
            base, bonus = self._base_bonus(lane)
            lane.power = min(1.0, base + bonus * lane.streak / self.config.reward_seconds) if self.state == "running" and self.safety == "allowed" and lane.finish_time is None else 0.0
            lane.max_power = max(lane.max_power, lane.power)

    def advance(self, now):
        if not math.isfinite(now) or now < self.now:
            raise ValueError("后台单调时间不可倒退")
        self._guards()
        while self.now < now - 1e-10:
            end = now
            for lane in self.lanes:
                if lane.valid:
                    end = min(end, lane.received + self.config.data_timeout)
            if self.state == "countdown":
                end = min(end, self.countdown_end)
            if self.state == "running" and self.activity == "training":
                end = min(end, self.now + self.duration - self.elapsed)
            dt = max(0.0, end - self.now)
            if self.state == "running":
                # Find first virtual crossing analytically (binary root of exact integral).
                crossings = []
                if self.activity == "racing":
                    for i, lane in enumerate(self.lanes):
                        scale = self.config.max_race_speed * self.config.virtual_distance_scale
                        if lane.valid and lane.position + self._integral(lane, dt) * scale >= self.distance:
                            lo, hi = 0.0, dt
                            for _ in range(45):
                                mid = (lo + hi) / 2
                                if lane.position + self._integral(lane, mid) * scale >= self.distance:
                                    hi = mid
                                else:
                                    lo = mid
                            crossings.append((hi, i))
                    if crossings:
                        dt = min(t for t, _ in crossings)
                        end = self.now + dt
                for lane in self.lanes:
                    if not lane.valid:
                        continue
                    lane.valid_seconds += dt
                    if lane.raw >= lane.reference:
                        lane.target_seconds += dt
                        lane.current_streak += dt
                        lane.best_streak = max(lane.best_streak, lane.current_streak)
                    else:
                        lane.current_streak = 0.0
                    if self.activity == "racing":
                        lane.position = min(self.distance, lane.position + self._integral(lane, dt) * self.config.max_race_speed * self.config.virtual_distance_scale)
                    _, bonus = self._base_bonus(lane)
                    lane.streak = min(self.config.reward_seconds, lane.streak + dt) if bonus else 0.0
                self.elapsed += dt
                self.now = end
                if crossings:
                    winners = [i for t, i in crossings if abs(t - dt) <= 1e-7]
                    for i in winners:
                        self.lanes[i].finish_time = self.elapsed
                        self.lanes[i].position = self.distance
                    self.result = "tie" if len(winners) == 2 else f"player_{winners[0]+1}"
                    self.transition("finished", "virtual_finish")
                elif self.activity == "training" and self.elapsed >= self.duration - 1e-9:
                    self.transition("finished", "duration_complete")
            else:
                self.now = end
            self._guards()
            if self.state == "countdown" and self.now >= self.countdown_end - 1e-9:
                self.transition("running", "countdown_complete")
            self._powers()
        self.now = now
        self._guards()
        self._powers()

    def snapshot(self):
        players = []
        for i, lane in enumerate(self.lanes, 1):
            row = asdict(lane)
            _, bonus = self._base_bonus(lane)
            boost_active = (self.activity == "racing" and self.state == "running"
                            and self.safety == "allowed" and lane.finish_time is None and bonus > 0)
            row.update(boost_active=boost_active,
                       boost_progress=min(1.0, max(0.0, lane.streak / self.config.reward_seconds)) if boost_active else 0.0)
            row.update(player=i, stable_ratio=100 * lane.target_seconds / lane.valid_seconds if lane.valid_seconds else None,
                       average=lane.total / lane.sample_count if lane.sample_count >= 2 else None,
                       trend=lane.last_value - lane.first_value if lane.sample_count >= 2 else None,
                       data_status="ok" if lane.sample_count >= 2 else "暂无足够数据")
            players.append(row)
        return {"session_id": self.session_id, "algorithm": ALGORITHM_VERSION, "mode": self.config.mode,
                "attention_thresholds": [self.config.start_threshold, self.config.high_focus_threshold],
                "activity": self.activity, "state": self.state, "safety": self.safety, "reason": self.reason,
                "elapsed": self.elapsed, "duration": self.duration, "distance": self.distance,
                "countdown": max(0, math.ceil(self.countdown_end - self.now)) if self.state == "countdown" else 0,
                "result": self.result, "players": players, "now": self.now, "last_rejection": self.last_rejection}

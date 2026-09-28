"""Single control owner; immutable view snapshots and bounded asynchronous persistence."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, Future
from collections import OrderedDict, deque
import json
import math
import queue
import threading
import time
import uuid

from .engine import Engine, ALGORITHM_VERSION, TERMINAL
from .storage import Store, export_session


@dataclass(frozen=True)
class DeviceFrame:
    lane: int
    raw: object = None
    sequence: object = None
    received: float = 0.0
    generation: int = 0
    connected: bool = False
    worn: object = None
    state: str = "off"
    calibration_progress: object = None
    device_baseline: object = None


def safe_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    return value


class BackendService:
    def __init__(self, config, activity="training", duration=60., distance=100., references=None,
                 output=None, clock=time.monotonic, environment=None, operator=None):
        self.config, self.clock = config, clock
        self.output = output or (lambda state: None)
        self.environment = environment or {}
        self.operator = operator
        self.operator_generation = None
        self.chart_points = [deque(maxlen=600), deque(maxlen=600)]
        self.chart_identity = [None, None]
        self.receipts = OrderedDict()
        self.receipt_owner = None
        self.owner_requests = 0
        self.bindings = list(range(1, config.players + 1))
        self.player_ids = [f"local-{i}" for i in self.bindings]
        self.recent_events = deque(maxlen=80)
        self.event_cursor = 0
        self.store = Store(config)
        self.frames = queue.Queue(config.storage_queue_size)
        self.intents = queue.Queue(32)
        self.view_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.started, self.failed = False, None
        self.exports = ThreadPoolExecutor(max_workers=1, thread_name_prefix="focus-export")
        try:
            self._create(activity, duration, distance, references)
        except Exception:
            self.store.close()
            self.exports.shutdown(wait=False)
            raise
        self.thread = threading.Thread(target=self._run, name="focus-control", daemon=True)

    def _create(self, activity, duration, distance, references=None):
        self.epoch = self.clock()
        self.start_utc = datetime.now(timezone.utc).isoformat()
        self.session_id = uuid.uuid4().hex
        self.engine = Engine(self.config, self.session_id, activity, duration, distance, references)
        self.ordinal = 0
        self.last_flush_wall = self.clock()
        self.journal = []
        self.metadata_pending = True
        self.terminal_ordinal = None
        self.incomplete = False
        self.recent_events.clear()
        for points in self.chart_points:
            points.clear()
        self.chart_identity = [None, None]
        self.event_cursor = 0
        self._publish_view()

    def start(self):
        if self.started:
            return False
        self.started = True
        self._flush(force=True)
        self.thread.start()
        return True

    def submit_frame(self, frame, absolute=False):
        value = dict(frame.__dict__) if isinstance(frame, DeviceFrame) else dict(frame)
        value = safe_json(value)
        value["_absolute"] = absolute
        try:
            self.frames.put_nowait(value)
            return True
        except queue.Full:
            self.failed = "acquisition_queue_overflow"
            return False

    def submit_intent(self, action, session_id=None, **options):
        # Every queued intent carries the ID at creation, including old callbacks.
        if self.stop_event.is_set():
            return False
        try:
            self.intents.put_nowait((action, session_id or self.session_id, safe_json(options), None))
            return True
        except queue.Full:
            self.failed = "intent_queue_overflow"
            return False

    def request(self, request_id, action, session_id, token, **options):
        """Return a receipt only after the control owner has decided the operation."""
        future = Future()
        envelope = (request_id, token, future)
        try:
            if self.stop_event.is_set():
                raise RuntimeError("stopping")
            self.intents.put_nowait((action, session_id, safe_json(options), envelope))
        except (queue.Full, RuntimeError):
            future.set_result({"ok": False, "reason": "service_busy", "request_id": request_id})
        return future

    def snapshot(self):
        with self.view_lock:
            snapshot = deepcopy(self.view)
            terminal_ordinal = self.view_terminal_ordinal
            incomplete = self.view_incomplete
        health = self._health()
        snapshot["storage"] = health
        snapshot["saved"] = bool(terminal_ordinal is not None and not incomplete and health["healthy"]
                                 and self.store.committed.get(snapshot["session_id"], -1) >= terminal_ordinal)
        snapshot["record_incomplete"] = incomplete
        return snapshot

    def _health(self):
        """Include records still held by the control owner in the lag window."""
        health = self.store.health()
        if self.journal:
            local_lag = max(0.0, self.clock() - self.last_flush_wall)
            health["lag_seconds"] = max(health["lag_seconds"], local_lag)
            if local_lag > self.config.storage_max_lag_seconds:
                health["healthy"] = False
                health["error"] = health["error"] or "控制记录缓冲超时"
        return health

    def export(self, session_id, directory="reports"):
        return self.exports.submit(export_session, self.store.path, session_id, directory)

    def _record(self, kind, payload):
        self.journal.append({"ordinal": self.ordinal, "t": self.engine.now, "kind": kind, "payload": payload})
        self.ordinal += 1

    def _advance(self, t):
        self.engine.advance(max(self.engine.now, t))
        self._record("advance", {"t": self.engine.now})

    def _intent(self, action, sid, options):
        accepted = self.engine.intent(action, sid, **options)
        self._record("intent", {"action": action, "session_id": sid, "options": options})
        return accepted

    def _publish_view(self):
        with self.view_lock:
            self.view = self.engine.snapshot()
            self.view_terminal_ordinal = self.terminal_ordinal
            self.view_incomplete = self.incomplete
            self.view["events"] = list(self.recent_events)
            self.view["bindings"] = list(self.bindings)
            self.view["player_ids"] = list(self.player_ids)
            self.view["session_kind"] = self.config.session_kind
            self.view["chart_points"] = [list(points) for points in self.chart_points[:self.config.players]]
            self.view["start_utc"] = self.start_utc
            self.view["published_monotonic"] = self.clock()
            self.view["data_timeout"] = self.config.data_timeout
            self.view["sample_ages_ms"] = [max(0, (self.clock() - self.epoch - l.received) * 1000) if l.valid else None for l in self.engine.lanes]

    def _flush(self, force=False):
        if not self.journal and not self.metadata_pending:
            return
        if not force and not self.metadata_pending and self.clock() - self.last_flush_wall < self.config.storage_flush_seconds:
            return
        snap = self.engine.snapshot()
        self._record("checkpoint", snap)
        batch = {"session_id": self.session_id, "start_utc": self.start_utc, "journal": self.journal,
                 "events": self.engine.events, "samples": self.engine.sample_rows, "snapshot": snap,
                 "incomplete": self.incomplete, "player_ids": self.player_ids}
        for event in self.engine.events:
            self.event_cursor += 1
            self.recent_events.append({**event, "cursor": self.event_cursor})
        if self.metadata_pending:
            batch["config"] = {"config": self.config.snapshot(), "config_sha256": self.config.digest,
                               "activity": self.engine.activity, "duration": self.engine.duration,
                               "distance": self.engine.distance, "references": [l.reference for l in self.engine.lanes],
                               "algorithm": ALGORITHM_VERSION, "environment": self.environment,
                               "bindings": self.bindings, "player_ids": self.player_ids}
        if self.store.submit(batch):
            self.last_flush_wall = self.clock()
            self.metadata_pending = False
            self.journal, self.engine.events, self.engine.sample_rows = [], [], []
            if snap["state"] in TERMINAL:
                self.terminal_ordinal = self.ordinal - 1
        else:
            self.failed = "storage_write_failed"
            self.incomplete = True
            # Bound buffers after a latched failure. Recovery requires process restart.
            self.journal, self.engine.events, self.engine.sample_rows = [], [], []

    def _run(self):
        next_tick = self.clock()
        try:
            while not self.stop_event.is_set():
                now = self.clock()
                if now < next_tick:
                    self.stop_event.wait(min(.05, next_tick - now))
                    continue
                next_tick = now + self.config.control_interval_ms / 1000
                self.step(now)
        except Exception as exc:
            self.failed = f"control_failure: {exc}"
            self.incomplete = True
            self._intent("fault", self.session_id, {"reason": self.failed})
            try:
                self._output()
            finally:
                self._flush(force=True)
                self._publish_view()
        finally:
            # Always send a zero-output final state, even when no page polls it.
            if self.engine.state not in TERMINAL:
                self._advance(self.clock() - self.epoch)
                self._intent("end", self.session_id, {})
            try:
                self._output()
            finally:
                self._flush(force=True)
                self._publish_view()

    def step(self, now):
        if self.operator is not None and (not self.operator.alive() or self.operator.generation != self.operator_generation) and self.engine.state in ("running", "countdown"):
            self._intent("operator_lost", self.session_id, {})
        active = self.engine.state not in TERMINAL
        health = self._health()
        if self.failed or not health["healthy"]:
            if self.engine.safety != "fault_locked":
                self.incomplete = True
                self._intent("fault", self.session_id, {"reason": self.failed or health["error"] or "storage_buffer_timeout"})
        # Drain a bounded snapshot of incoming frames, preserving every acquisition frame.
        frames = []
        for _ in range(self.frames.qsize()):
            frame = self.frames.get_nowait()
            absolute = frame.pop("_absolute", False)
            if absolute:
                frame["received"] -= self.epoch
            frames.append(frame)
        frames.sort(key=lambda f: f.get("received", 0))
        for frame in frames:
            if frame["lane"] not in self.bindings:
                continue
            frame["lane"] = self.bindings.index(frame["lane"]) + 1
            # Frames acquired before this session cannot supply its first input.
            if frame.get("received", 0) < 0:
                continue
            if active and not self.incomplete:
                self._advance(min(now - self.epoch, max(self.engine.now, frame.get("received", 0))))
                lane = frame.pop("lane")
                self.engine.feed(lane, frame)
                self._record("frame", {"lane": lane, "frame": frame})
        if active:
            self._advance(now - self.epoch)
        for _ in range(self.intents.qsize()):
            action, sid, options, envelope = self.intents.get_nowait()
            self._command(action, sid, options, envelope)
        result = self._output()
        if result:
            self._intent("fault", self.session_id, {"reason": str(result)})
            self._output()
        # No repeated terminal writes unless there are new intents/events.
        self._flush(force=self.engine.state in TERMINAL)
        for i, lane in enumerate(self.engine.lanes):
            identity = (self.session_id, lane.generation, lane.sequence, lane.valid, self.engine.state)
            if identity != self.chart_identity[i]:
                live = lane.valid and self.engine.state == "running"
                self.chart_points[i].append([self.engine.now, lane.raw if live else None, lane.smoothed if live else None])
                self.chart_identity[i] = identity
        self._publish_view()

    def _command(self, action, sid, options, envelope):
        fingerprint = json.dumps([action, sid, options], sort_keys=True)
        request_id, token, future = envelope if envelope else (None, None, None)
        key = (token, request_id)
        if envelope and future.cancelled():
            return
        if envelope and key in self.receipts:
            old_fingerprint, result = self.receipts[key]
            future.set_result(result if fingerprint == old_fingerprint else {"ok": False, "reason": "idempotency_conflict", "request_id": request_id})
            return
        reason = ""
        ok = False
        if envelope and self.operator is not None and not self.operator.authorized(token):
            reason = "operator_required"
        elif envelope and token == self.receipt_owner and self.owner_requests >= 1024 and action not in ("end", "emergency"):
            reason = "operation_limit_release_and_reclaim"
        elif action == "prepare" and sid == self.session_id and self.engine.state in ("preparing", "finished", "aborted") and self.engine.safety == "inhibited" and not self.incomplete:
            try:
                config = replace(self.config, players=options.get("players", self.config.players), session_kind=options.get("session_kind", self.config.session_kind))
                activity = options.get("activity", self.engine.activity)
                duration, distance = options.get("duration", self.engine.duration), options.get("distance", self.engine.distance)
                references = options.get("references")
                bindings = options.get("bindings", list(range(1, config.players + 1)))
                players = options.get("player_ids", [f"local-{i}" for i in range(1, config.players + 1)])
                if activity == "racing" and config.players != 2:
                    raise ValueError("竞速需要两人")
                if len(bindings) != config.players or len(set(bindings)) != len(bindings) or any(type(v) is not int or v not in (1, 2) for v in bindings):
                    raise ValueError("头环绑定必须唯一且为 1 或 2")
                if len(players) != config.players or len(set(players)) != len(players) or any(not isinstance(p, str) or not p.strip() or len(p) > 48 for p in players):
                    raise ValueError("玩家编号必须唯一、非空且至多 48 字符")
                Engine(config, "validate", activity, duration, distance, references)
                if self.engine.state == "preparing":
                    self._intent("end", sid, {})
                self._flush(force=True)
                if not self.incomplete:
                    self.config, self.bindings, self.player_ids = config, bindings, players
                    self._create(activity, duration, distance, references)
                    ok = True
                else:
                    reason = "storage_write_failed"
            except (ValueError, TypeError) as exc:
                reason = str(exc)
        else:
            ok = self._intent(action, sid, options)
            if ok and action in ("start", "resume") and self.operator is not None:
                self.operator_generation = self.operator.generation
            reason = self.engine.last_rejection if not ok else ""
        if envelope:
            if self.operator is None or self.operator.authorized(token):
                if token != self.receipt_owner:
                    self.receipt_owner, self.owner_requests = token, 0
                self.owner_requests += 1
            result = {"ok": ok, "reason": reason, "request_id": request_id, "session_id": self.session_id, "state": self.engine.state}
            self.receipts[key] = (fingerprint, result)
            while len(self.receipts) > 1024:
                self.receipts.popitem(last=False)
            future.set_result(result)

    def _output(self):
        state = self.engine.snapshot()
        state["bindings"] = self.bindings
        return self.output(state)

    def stop(self, reason="application_exit"):
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.started:
            self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.failed = "control_thread_did_not_exit"
            return  # Caller still performs the independent GPIO emergency stop.
        if not self.started:
            if self.engine.state not in TERMINAL:
                self._intent("end", self.session_id, {})
            self._output()
            self._flush(force=True)
            self._publish_view()
        self.store.close()
        self.exports.shutdown(wait=False)

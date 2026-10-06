"""Loopback-only API. Control decisions remain on the backend control thread."""
import asyncio
import io
import json
import sqlite3
import time
import uuid
import zipfile
from collections import deque, OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .runtime import OperatorLease
from .serializers import clean
from .access import ReportAccess

ROOT = Path(__file__).resolve().parent
ACTIONS = {"prepare", "start", "pause", "resume", "end", "emergency", "reset", "finish_visit"}
OPTIONS = {"activity", "duration", "distance", "players", "references", "bindings", "player_ids", "session_kind", "confirmed", "visit_action", "continuing_lanes"}


def create_app(service, lease=None, port=8000, staff_pin=None):
    lease = lease or service.operator or OperatorLease(service.config.operator_timeout)
    service.operator = lease
    app = FastAPI(title="Focus Local", version="youth-ui-v2", docs_url=None, redoc_url=None)
    app.state.service, app.state.lease = service, lease
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    exports = Path(service.store.path).parent / "exports"
    render_latencies = deque(maxlen=2000)
    access = ReportAccess(service, staff_pin)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
            return JSONResponse({"ok": False, "reason": "local_access_only"}, status_code=403)
        if (origin and origin not in origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"ok": False, "reason": "origin_rejected"}, status_code=403)
        if request.method == "POST" and (request.headers.get("x-focus-client") != "web" or int(request.headers.get("content-length", "0")) > 8192):
            return JSONResponse({"ok": False, "reason": "invalid_request"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.exception_handler(HTTPException)
    async def error(request, exc):
        return JSONResponse({"ok": False, "reason": str(exc.detail)}, status_code=exc.status_code)

    def current():
        state = service.snapshot()
        if not state.get("visit_open", True):
            from dataclasses import asdict
            from backend.engine import Lane
            # Closing a visit revokes live snapshot data as well as saved reports.
            state["players"] = [{**asdict(Lane()), "player": i+1, "average": None,
                                 "stable_ratio": None, "trend": None, "data_status": "到访已结束"}
                                for i in range(len(state["players"]))]
            state.update(player_ids=[""]*len(state["players"]), visit_ids=[], participant_ids=[],
                         events=[], chart_points=[[] for _ in state["players"]], elapsed=0,
                         result=None, sample_ages_ms=[None]*len(state["players"]))
        state["operator"] = lease.status()
        state["control_alive"] = service.thread.is_alive() and not service.failed
        return clean(state)

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/api/health")
    def health():
        s = current()
        return {"ok": True, "ready": s["control_alive"] and s["storage"]["healthy"], "mode": s["mode"]}

    @app.get("/api/session")
    def session():
        return {"ok": True, "snapshot": current()}

    @app.post("/api/control/claim")
    def claim(payload: dict):
        if not isinstance(payload.get("connection"), str) or not isinstance(payload.get("request_id"), str):
            raise HTTPException(400, "connection_and_request_id_required")
        token = lease.claim(payload["connection"], payload["request_id"])
        if not token:
            raise HTTPException(409, "operator_busy_or_disconnected")
        return {"ok": True, "token": token}

    @app.get("/api/preferences")
    def preferences():
        from .preferences import preferences
        return {"ok": True, "preset": preferences(service.store.path)}

    @app.get("/api/players")
    def players(request: Request):
        from .preferences import players
        if access.staff(request):
            return {"ok": True, "players": players(service.store.path), "staff": True}
        s = current()
        return {"ok": True, "staff": False, "players": [
            {"id": pid, "nickname": "蓝色访客" if i == 0 else "橙色访客", "avatar": "wave" if i == 0 else "star"}
            for i, pid in enumerate(s["player_ids"]) if s.get("visit_open") and s.get("visitor_mode")]}

    @app.post("/api/staff/unlock")
    def unlock(payload: dict):
        if not lease.authorized(payload.get("token")):
            raise HTTPException(403, "operator_required")
        return {"ok": True, "staff_token": access.unlock(payload.get("pin"))}

    def settings_access(payload):
        if not lease.authorized(payload.get("token")):
            raise HTTPException(403, "operator_required")
        s = current()
        if s["state"] not in ("preparing", "finished", "aborted") or s["safety"] != "inhibited":
            raise HTTPException(409, "settings_locked_during_session")
        if not s["storage"]["healthy"]:
            raise HTTPException(503, "storage_write_failed")

    @app.post("/api/preferences")
    def save_preferences(payload: dict):
        from .preferences import save_preset
        settings_access(payload)
        try:
            return {"ok": True, "preset": save_preset(service.store.path, payload.get("preset", {}))}
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        except sqlite3.Error:
            raise HTTPException(503, "storage_write_failed")

    @app.post("/api/players")
    def save_player(payload: dict, request: Request):
        from .preferences import save_player
        settings_access(payload)
        access.require_staff(request)
        try:
            return {"ok": True, "player": save_player(service.store.path, payload.get("player", {}))}
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        except sqlite3.Error:
            raise HTTPException(503, "storage_write_failed")

    @app.post("/api/control/release")
    def release(payload: dict):
        return {"ok": lease.release(payload.get("token"))}

    @app.post("/api/session/{sid}/action")
    async def action(sid: str, payload: dict, request: Request):
        action, request_id = payload.get("action"), payload.get("request_id")
        if action not in ACTIONS or not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            raise HTTPException(400, "invalid_action_or_request_id")
        token = payload.get("token")
        if not isinstance(token, str) or len(token) > 128:
            raise HTTPException(400, "invalid_token")
        options = {k: v for k, v in payload.items() if k not in {"action", "request_id", "token"}}
        if not set(options).issubset(OPTIONS):
            raise HTTPException(400, "unknown_option")
        if "player_ids" in options:
            access.require_staff(request)
        future = service.request(request_id, action, sid, token, **options)
        try:
            # Shield: timeout/disconnection cannot cancel a future owned by control.
            return clean(await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), 2))
        except asyncio.TimeoutError:
            return JSONResponse({"ok": False, "reason": "result_pending_retry_same_id", "request_id": request_id}, status_code=202)

    @app.get("/api/sessions")
    def history(request: Request, player_id: Optional[str] = None, date_from: Optional[str] = None,
                date_to: Optional[str] = None, condition: Optional[str] = None, limit: int = 50):
        from .queries import history_rows
        try:
            rows = history_rows(service.store.path, player_id, date_from, date_to, condition, limit)
            return {"ok": True, "sessions": [r for r in rows if access.allowed(r["session_id"], request)], "staff": access.staff(request)}
        except ValueError:
            raise HTTPException(400, "日期必须为 YYYY-MM-DD")

    @app.get("/api/sessions/{sid}/report")
    def report(sid: str, request: Request):
        from .queries import report_data
        access.require_report(sid, request)
        try:
            return {"ok": True, "report": clean(report_data(service.store.path, sid))}
        except KeyError:
            raise HTTPException(404, "report_not_ready")

    @app.post("/api/sessions/{sid}/export")
    async def export(sid: str, payload: dict, request: Request):
        access.require_report(sid, request)
        if not lease.authorized(payload.get("token")):
            raise HTTPException(403, "operator_required")
        if len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
            raise HTTPException(400, "invalid_session_id")
        try:
            paths = await asyncio.wrap_future(service.export(sid, exports))
            return {"ok": True, "files": [f"/api/download/{p.name}" for p in paths]}
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/download/{name}")
    def download(name: str, request: Request):
        if Path(name).name != name or Path(name).suffix not in (".csv", ".json") or not (exports / name).is_file():
            raise HTTPException(404, "file_not_found")
        access.require_report(Path(name).stem, request)
        return FileResponse(exports / name, filename=name)

    @app.post("/api/sessions/{sid}/analysis/retry")
    def retry_analysis(sid: str, payload: dict, request: Request):
        from contextlib import closing
        access.require_report(sid, request)
        if not lease.authorized(payload.get("token")):
            raise HTTPException(403, "operator_required")
        # Bounded retries across requests and restarts, no duplicate cloud jobs.
        with closing(sqlite3.connect(str(service.store.path), timeout=.1)) as db, db:
            count = db.execute("UPDATE analysis_jobs SET status='ai_pending',next_attempt=0 WHERE session_id=? AND status='template' AND attempts<2 AND error IS NOT NULL", (sid,)).rowcount
        return {"ok": True, "queued": count}

    @app.get("/api/maintenance")
    def maintenance():
        from app import environment
        return {"ok": True, "version": "youth-ui-v2", "environment": environment(),
                "config": service.config.snapshot(), "snapshot": current(),
                "diagnostics_note": "只读采集状态；运行中不另开串口。需要独立诊断时先停止服务。"}

    @app.get("/api/maintenance/metrics")
    def metrics(since: float = 0):
        values = sorted(value for stamp, value in render_latencies if stamp >= since)
        return {"ok": True, "samples": len(values), "p95_ms": values[min(len(values)-1, int(len(values)*.95))] if values else None,
                "clock": time.monotonic(), "metric": "adapter_receive_to_browser_animation_frame_ack_upper_bound_ms", "headband_latency_included": False}

    @app.get("/api/maintenance/logs")
    def logs():
        # Bounded export; never package patient/sample records with logs.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            folder = Path(service.store.path).parent
            for path in sorted(folder.glob("focus.log*"))[:6]:
                with path.open("rb") as f:
                    f.seek(max(0, path.stat().st_size - service.config.log_max_bytes))
                    archive.writestr(path.name, f.read(service.config.log_max_bytes))
            archive.writestr("status.json", json.dumps(clean({"config": service.config.snapshot(), "snapshot": current()}), ensure_ascii=False))
        return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="focus-logs.zip"'})

    @app.websocket("/ws")
    async def websocket(socket: WebSocket):
        if socket.headers.get("origin") not in origins or (socket.client and socket.client.host not in ("127.0.0.1", "::1", "testclient")):
            await socket.close(code=1008)
            return
        await socket.accept()
        connection = uuid.uuid4().hex
        lease.connect(connection)
        packets = OrderedDict()
        async def receiver():
            while True:
                message = await socket.receive_json()
                if isinstance(message, dict) and message.get("type") == "heartbeat":
                    ok = lease.heartbeat(message.get("token"), connection)
                    await socket.send_json({"type": "heartbeat", "ok": ok})
                elif isinstance(message, dict) and message.get("type") == "rendered":
                    sent = packets.pop(message.get("packet_id"), {})
                    for key in message.get("keys", [])[:2]:
                        if key in sent:
                            render_latencies.append((time.monotonic(), max(0, (time.monotonic() - sent[key]) * 1000)))
        task = asyncio.create_task(receiver())
        try:
            await socket.send_json({"type": "hello", "connection": connection})
            while not task.done():
                state = current()
                ages = [max(0, (time.monotonic() - service.epoch - p["received"]) * 1000) if p["valid"] else None for p in state["players"]]
                packet_id = uuid.uuid4().hex
                packets[packet_id] = {f"{state['session_id']}:{i}:{p['generation']}:{p['sequence']}": service.epoch+p['received'] for i,p in enumerate(state['players']) if p['valid']}
                while len(packets) > 32:
                    packets.popitem(last=False)
                await socket.send_json({"type": "snapshot", "packet_id": packet_id, "snapshot": state, "sample_ages_ms": ages})
                await asyncio.sleep(service.config.web_push_interval)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            lease.disconnect(connection)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app

"""Kiosk visit scope and explicit, short-lived staff access."""
from contextlib import closing
import hmac
import os
import secrets
import time

from fastapi import HTTPException
from backend.storage import _read_only


class ReportAccess:
    def __init__(self, service, pin=None):
        self.service = service
        self.pin = os.environ.get("FOCUS_STAFF_PIN", "") if pin is None else pin
        self.tokens = {}
        self.failures = []

    def staff(self, request):
        token = request.headers.get("x-focus-staff", "")
        now = time.monotonic()
        self.tokens = {k: v for k, v in self.tokens.items() if v[0] > now and v[1] == self.epoch()}
        return token in self.tokens

    def epoch(self):
        state = self.service.snapshot()
        return (state["session_id"], state.get("visit_open"))

    def unlock(self, pin):
        now = time.monotonic()
        self.failures = [t for t in self.failures if now-t < 60]
        if len(self.failures) >= 5:
            raise HTTPException(429, "请稍后再试工作人员口令")
        if len(self.pin) < 6:
            raise HTTPException(403, "请先在服务端设置至少六位的 FOCUS_STAFF_PIN")
        if not isinstance(pin, str) or not hmac.compare_digest(pin.encode(), self.pin.encode()):
            self.failures.append(now)
            raise HTTPException(403, "工作人员口令错误")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (now+300, self.epoch())
        if len(self.tokens) > 8:
            self.tokens.pop(next(iter(self.tokens)))
        return token

    def require_staff(self, request):
        if not self.staff(request):
            raise HTTPException(403, "需要工作人员解锁")

    def visits(self):
        s = self.service.snapshot()
        return set(v for v in s.get("visit_ids", []) if v) if s.get("visit_open") else set()

    def allowed(self, sid, request):
        if self.staff(request):
            return True
        visits = self.visits()
        if not visits:
            return False
        with closing(_read_only(self.service.store.path)) as db:
            rows = db.execute("SELECT visit_id FROM participant_identity WHERE session_id=?", (sid,)).fetchall()
        # Whole reports contain both lanes; deny if even one belongs to a past guest.
        return bool(rows) and all(v in visits for (v,) in rows)

    def require_report(self, sid, request):
        if not self.allowed(sid, request):
            raise HTTPException(403, "这份记录不属于当前到访，请工作人员解锁查看")

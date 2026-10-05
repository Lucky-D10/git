"""Local-only control lease and read-only WebSocket fan-out."""
from __future__ import annotations

import secrets
import threading
import time


class OperatorLease:
    """At most one browser may submit control intents at a time."""

    def __init__(self, timeout=2.0, clock=time.monotonic):
        self.timeout = timeout
        self.clock = clock
        self.lock = threading.RLock()
        self.token = None
        self.deadline = 0.0
        self.generation = 0
        self.connection = None
        self.connections = set()
        self.claim_id = None

    def connect(self, connection):
        with self.lock:
            self.connections.add(connection)

    def disconnect(self, connection):
        with self.lock:
            self.connections.discard(connection)
            if self.connection == connection:
                self.deadline = 0.0

    def claim(self, connection=None, request_id=None):
        with self.lock:
            if connection is not None and connection not in self.connections:
                return None
            now = self.clock()
            if request_id and request_id == self.claim_id and connection == self.connection and self.alive():
                return self.token
            if self.token is not None and now < self.deadline:
                return None
            self.token = secrets.token_urlsafe(24)
            self.generation += 1
            self.connection, self.claim_id = connection, request_id
            self.deadline = now + self.timeout
            return self.token

    def authorized(self, token):
        with self.lock:
            return bool(token and token == self.token and self.clock() < self.deadline
                        and (self.connection is None or self.connection in self.connections))

    def heartbeat(self, token, connection=None):
        with self.lock:
            if self.connection is not None and connection != self.connection:
                return False
            if not self.authorized(token):
                return False
            self.deadline = self.clock() + self.timeout
            return True

    def release(self, token):
        with self.lock:
            if token == self.token:
                self.token, self.deadline = None, 0.0
                return True
            return False

    def alive(self):
        with self.lock:
            return self.authorized(self.token)

    def status(self):
        with self.lock:
            return {"claimed": self.alive(), "expires_in": max(0.0, self.deadline - self.clock())}

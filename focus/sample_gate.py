"""Vendor identity gate. State-only changes never establish sample freshness."""
import math


class SnapshotGate:
    def __init__(self):
        self.last_token = None
        self.last_state = None
        self.reason = "unverified_identity"
        self.new_sample = False

    def accept(self, snapshot, state):
        seq, stamp = getattr(snapshot, "seq", None), getattr(snapshot, "updated_at", None)
        def usable(value):
            return type(value) in (int, float) and math.isfinite(value) and value > 0
        token = ("seq", seq) if usable(seq) else ("timestamp", stamp) if usable(stamp) else None
        self.new_sample = False
        if token is None:
            self.reason = "unverified_identity"
        elif self.last_token is None or token[0] != self.last_token[0] or token[1] > self.last_token[1]:
            self.new_sample, self.reason, self.last_token = True, "new_sample", token
        else:
            self.reason = "duplicate" if token == self.last_token else "out_of_order"
        changed = state != self.last_state
        self.last_state = state
        return self.new_sample or changed

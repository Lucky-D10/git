"""Session rules and audit events, independent of Tk and hardware."""
from dataclasses import asdict, dataclass
import logging
import time
from settings import ACTIVE


@dataclass(frozen=True)
class Rules:
    version: str = "stage1-v1"
    players: int = 2
    kind: str = "experience"
    dual_loss: str = "continue"
    score_source: str = "virtual"
    pause_counts: bool = False
    restart_after_emergency: bool = True

    @classmethod
    def from_config(cls, config):
        return cls(players=config.players, kind=config.session_kind,
                   dual_loss="abort" if config.session_kind == "formal" else "continue")


class Session:
    def __init__(self, config=ACTIVE, clock=time.monotonic):
        self.config = config
        self.rules = Rules.from_config(config)
        self.clock = clock
        self.started_at = clock()
        self.events = []
        self.last_valid = None
        self.ever_valid = False
        self.aborted = False
        self.event("session_start")

    def event(self, name, **details):
        row = {"seconds": round(self.clock() - self.started_at, 6), "event": name, **details}
        self.events.append(row)
        logging.getLogger("EEGSystem").info("[%s] %s", self.config.mode, row)

    def observe(self, samples):
        valid = tuple(s.valid for s in samples[:self.rules.players])
        self.ever_valid = self.ever_valid or any(valid)
        if valid != self.last_valid:
            previous = self.last_valid
            for i, status in enumerate(valid):
                if previous is None or status != previous[i]:
                    self.event("signal_recovered" if status else "signal_lost", lane=i + 1)
            self.last_valid = valid
        if self.ever_valid and not any(valid) and self.rules.dual_loss == "abort" and not self.aborted:
            self.aborted = True
            self.event("session_aborted", reason="all_signals_lost")
        return self.aborted

    def metadata(self):
        return {"runtime_mode": self.config.mode, "config": self.config.snapshot(),
                "config_sha256": self.config.digest, "rules": asdict(self.rules),
                "events": [dict(event) for event in self.events], "aborted": self.aborted}


current = None


def begin():
    global current
    current = Session()
    return current


def event(name, **details):
    if current is not None:
        current.event(name, **details)


def observe(samples):
    return current.observe(samples) if current is not None else False


def metadata():
    return current.metadata() if current is not None else {
        "runtime_mode": ACTIVE.mode, "config": ACTIVE.snapshot(),
        "config_sha256": ACTIVE.digest, "rules": asdict(Rules.from_config(ACTIVE)), "events": []}

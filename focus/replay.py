"""Fixed input scenarios exercise the production engine without threads or GPIO."""
import json
from pathlib import Path
from backend.engine import Engine
from settings import Config


def scenarios():
    return json.loads((Path(__file__).parent / "replay_samples.json").read_text(encoding="utf-8"))


def run_scenario(name, rows):
    config = Config(mode="simulation", countdown_seconds=.1, calibration_timeout=1)
    engine = Engine(config, "replay-" + name, "training", duration=60)
    trace = []
    for row in rows:
        engine.advance(row["t"])
        if row["type"] == "frame":
            engine.feed(row["lane"], row["frame"])
        elif row["type"] == "intent":
            engine.intent(row["action"], row.get("session_id", engine.session_id), **row.get("options", {}))
        elif row["type"] != "tick":
            raise ValueError("Unknown scenario action")
        trace.append(engine.snapshot())
    accepted = [sum(s["lane"] == lane and s["valid"] for s in engine.sample_rows) for lane in (1,2)]
    return {"scenario": name, "valid_samples": accepted, "state": engine.state,
            "final_power": [p["power"] for p in trace[-1]["players"]],
            "trace": trace, "events": engine.events}


def run_all():
    return {name: run_scenario(name, rows) for name, rows in scenarios().items()}


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))

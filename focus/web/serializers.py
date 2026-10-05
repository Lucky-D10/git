"""JSON-safe response helpers kept independent of FastAPI."""
import json
import math


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


def fingerprint(action, session_id, options):
    return json.dumps([action, session_id, options], sort_keys=True, ensure_ascii=False)

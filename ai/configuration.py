"""Load trusted local AI settings without replacing service environment values."""
import os
from pathlib import Path

LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.deepseek"
ALLOWED = {
    "FOCUS_AI_PROVIDER", "FOCUS_AI_MODEL", "DEEPSEEK_API_KEY",
    "FOCUS_AI_BASE_URL", "FOCUS_AI_TIMEOUT", "FOCUS_AI_ALLOW_SIMULATION",
}


def load_local_env(path=None, *, overwrite=False, required=False):
    path = Path(path) if path is not None else LOCAL_ENV_FILE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        if required:
            raise
        return False
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in ALLOWED | {"FOCUS_STAFF_PIN"}:
            # Never include the offending line, which could contain a secret.
            raise ValueError("Invalid local AI configuration field")
        if name not in ALLOWED:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    # Validate the entire file before changing the process environment.
    for name, value in values.items():
        if overwrite:
            os.environ[name] = value
        else:
            os.environ.setdefault(name, value)
    return True

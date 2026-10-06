"""Load the ignored local DeepSeek configuration, then run the normal Web entry."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ALLOWED = {
    "FOCUS_AI_PROVIDER", "FOCUS_AI_MODEL", "DEEPSEEK_API_KEY",
    "FOCUS_AI_BASE_URL", "FOCUS_AI_TIMEOUT", "FOCUS_AI_ALLOW_SIMULATION",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--allow-simulation", action="store_true")
    options, arguments = parser.parse_known_args()
    config_file = ROOT / ".env.deepseek"
    if not config_file.is_file():
        raise SystemExit("Missing local .env.deepseek configuration.")
    for line in config_file.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in ALLOWED:
            raise SystemExit("Invalid local DeepSeek configuration field.")
        os.environ[name] = value.strip()
    if options.allow_simulation:
        os.environ["FOCUS_AI_ALLOW_SIMULATION"] = "1"
    from ai.provider import ProviderConfig
    config = ProviderConfig.from_env()
    if not config.enabled:
        raise SystemExit("DeepSeek configuration is incomplete or invalid.")
    if options.check:
        print("DeepSeek configuration loaded; model=" + config.model)
        print("Simulation cloud calls: " + ("enabled" if config.allow_simulation else "disabled"))
        print("Local check only; no API request sent.")
        return
    from app import main as run_app
    run_app(["web", *arguments])


if __name__ == "__main__":
    main()

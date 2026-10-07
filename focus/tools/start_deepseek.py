"""Load the ignored local DeepSeek configuration, then run the normal Web entry."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.configuration import load_local_env


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--allow-simulation", action="store_true")
    options, arguments = parser.parse_known_args()
    try:
        load_local_env(required=True)
    except (OSError, ValueError):
        raise SystemExit("Local .env.deepseek is missing, unreadable or invalid.") from None
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

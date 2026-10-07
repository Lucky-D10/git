"""Check server AI configuration; --live sends a synthetic example, never visitor data."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Read a trusted local KEY=value configuration file")
    parser.add_argument("--live", action="store_true", help="Make a paid synthetic request; retry validation failure once (at most two requests)")
    args = parser.parse_args()
    from ai.configuration import load_local_env
    try:
        load_local_env(args.env_file, overwrite=bool(args.env_file), required=bool(args.env_file))
    except (OSError, ValueError):
        print("Configuration file could not be read or contains unsupported fields.")
        return 2
    from ai.provider import ProviderConfig, ProviderError, generate
    from ai.validator import VALIDATION_FEEDBACK, ValidationError, validate
    from analytics.coaching import coaching
    try:
        config = ProviderConfig.from_env()
        enabled = config.enabled
    except ValueError:
        print("Invalid provider URL or configuration.")
        return 2
    print(json.dumps({"provider": config.provider, "model": config.model,
                      "key_present": bool(config.api_key), "enabled": enabled,
                      "simulation_allowed": config.allow_simulation}, ensure_ascii=False))
    if not enabled:
        print("AI configuration is incomplete; check provider, model, key and HTTPS base URL.")
        return 2
    if not args.live:
        print("Local configuration check passed. No API request was sent.")
        return 0
    metrics = dict(valid_seconds=60., coverage=1., active_seconds=60., reference=50., target_ratio=.6,
                   best_streak=8., weighted_average=62., iqr=15., target_bouts=2,
                   segments=[dict(average=v, coverage=1.) for v in (60., 62., 64.)])
    facts = [
        {"id": "quality", "text": "人工模拟记录：有效时长 60 秒，覆盖率 100%。"},
        {"id": "target", "text": "门槛 50，达标率 60%，最长连续达标 8 秒。"},
        {"id": "level", "text": "时间加权平均 62，四分位距 15。"},
        {"id": "segments", "text": "前中后段平均读数分别为 60、62、64。"},
    ]
    report = {"scope": "single_session", "mode": "simulation", "facts": facts,
              "limitations": ["仅为人工模拟记录，不对应真实参与者，不用于能力或健康评价。"],
              **coaching(metrics, True, facts)}
    for attempt in range(2):
        try:
            result = validate(generate(config, report), report)
            break
        except (ProviderError, ValueError) as exc:
            # Never print provider bodies, HTTP headers or credentials.
            code = str(exc)
            safe_code = code if code in VALIDATION_FEEDBACK or isinstance(exc, ProviderError) else "validation_failed"
            print("Live check failed: " + safe_code)
            if isinstance(exc, ValidationError):
                print("Validation field=" + exc.field + "; rule=" + exc.rule)
            if isinstance(exc, ValueError) and code in VALIDATION_FEEDBACK and attempt == 0:
                report["_validation_error"] = code
                print("Retrying once with validation feedback; the same checks still apply.")
                continue
            return 1
    print("Live synthetic request passed transport and content validation.")
    print(json.dumps({"summary": result["summary"], "observation_count": len(result["observations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Ground numbers in evidence placeholders and keep practice goals local."""
import re


def validate(value, report):
    if not isinstance(value, dict) or set(value) != {"summary", "observations", "goal_id", "recommendation_ids", "encouragement"}:
        raise ValueError("invalid_schema")
    def wording(text, limit, tokens=None):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= limit:
            raise ValueError("unsupported_claim")
        placeholders = re.findall(r"\{([^{}]+)\}", text)
        if any(p not in (tokens or {}) for p in placeholders):
            raise ValueError("unknown_evidence")
        prose = re.sub(r"\{[^{}]+\}", "", text)
        if re.search(r"(?:说明|表明|代表).*(?:跟住|跟随|认真|走神|心理)|你.*(?:全程|从头到尾|保持了稳定)", prose):
            raise ValueError("unsupported_claim")
        if re.search(r"[\d<>{}%％]|百分之|百分点|[零〇一二两三四五六七八九十百千万]+(?:秒|分钟|分之|成)|超过.*人|智商|诊断|患有|治愈|多动症|抑郁|焦虑症|疲劳|天生|一定|证明|笨|懒|不如别人|差生|学霸|不够努力|比别人|保证|你很聪明|你很努力|你不认真|你很认真|成绩会|成绩提高", prose):
            raise ValueError("unsupported_claim")
        if report["scope"] == "single_session" and re.search(r"上次|以前|以往|历史|一贯|一直|进步|退步|提升|改善", text):
            raise ValueError("unsupported_history")
        result = text.strip()
        for token in placeholders:
            result = result.replace("{" + token + "}", tokens[token])
        return result
    summary = wording(value["summary"], 40)
    rows = value["observations"]
    if not isinstance(rows, list) or not 2 <= len(rows) <= 3:
        raise ValueError("invalid_observations")
    facts = {f["id"]: f for f in report["facts"]}
    observations = []
    seen = set()
    grounded = False
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"evidence_id", "text"} or not isinstance(row["evidence_id"], str) or row["evidence_id"] not in facts:
            raise ValueError("unknown_evidence")
        if row["evidence_id"] == "comparison" and report["scope"] != "same_visit":
            raise ValueError("unsupported_history")
        if row["evidence_id"] in seen:
            raise ValueError("invalid_observations")
        seen.add(row["evidence_id"])
        text = wording(row["text"], 160, report["display_values"].get(row["evidence_id"], {}))
        grounded = grounded or "{" in row["text"]
        observations.append({"evidence_id": row["evidence_id"], "text": text})
    if not grounded:
        raise ValueError("invalid_observations")
    if value["goal_id"] != report["goal"]["id"]:
        raise ValueError("unknown_recommendation")
    ids = value["recommendation_ids"]
    allowed = {r["id"]: r for r in report["suggestions"]}
    if not isinstance(ids, list) or not 2 <= len(ids) <= 3 or any(not isinstance(i, str) or i not in allowed for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("unknown_recommendation")
    return {"summary": summary, "observations": observations, "suggestions": [allowed[i] for i in ids],
            "encouragement": wording(value["encouragement"], 100)}

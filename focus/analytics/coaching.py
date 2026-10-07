"""Versioned practice suggestions, not ability scores or clinical thresholds."""
import math


def coaching(metrics, eligible, facts, comparison=None):
    m = metrics
    fact_ids = {f["id"] for f in facts}
    values = {"quality": {"有效时长": "%.1f 秒" % m["valid_seconds"],
                          "覆盖率": "%.1f%%" % (m["coverage"] * 100)}}
    if "target" in fact_ids:
        values["target"] = {"本轮门槛": "%g" % m["reference"],
                            "达标率": "%.1f%%" % (m["target_ratio"] * 100),
                            "连续达标": "%.1f 秒" % m["best_streak"]}
        values["level"] = {"平均读数": "%.1f" % m["weighted_average"], "四分位距": "%.1f" % m["iqr"]}
    if "segments" in fact_ids:
        values["segments"] = {name: "%.1f" % s["average"] for name, s in
                              zip(("前段读数", "中段读数", "后段读数"), m["segments"])}
    if "comparison" in fact_ids and comparison:
        values["comparison"] = {"达标率变化": "%+.1f 个百分点" % comparison["target_ratio_delta_pp"]}

    def step(id, text, evidence):
        return {"id": id, "text": text, "evidence_ids": evidence}

    if not eligible:
        signal_problem = m["coverage"] < .8
        focus = "signal" if signal_problem else "complete_round"
        goal = {"id": focus, "title": "先让记录完整起来", "metric": None, "baseline": None,
                "target": None, "unit": None, "evidence_ids": ["quality"],
                "text": "下一轮先请老师确认头环信号，再按页面预设完成体验；这次不追求更高读数。",
                "why": "目前的有效记录还不足以设置成绩目标，缺少数据不等于你做得不好。"}
        steps = [step("check_signal", "开始前请老师检查头环是否戴好、连接是否正常；看到准备完成后再开始。", ["quality"]),
                 step("comfortable_round", "选一个舒服的坐姿，按页面提示做任务；不舒服或想停止时，告诉老师，不必为了完成记录勉强继续。", ["quality"])]
        return {"focus": focus, "summary": "先准备好，再试一次", "goal": goal, "suggestions": steps,
                "encouragement": "愿意尝试就值得肯定。一次记录不完整，不是你的成绩，也不会给你贴标签。",
                "display_values": values}

    ratio = m["target_ratio"]
    end_lower = "segments" in fact_ids and m["segments"][2]["average"] <= m["segments"][0]["average"] - 8
    variable = m["iqr"] >= 25 and m["target_bouts"] >= 3
    if ratio < .3:
        focus, title = "first_steps", "先找一个短短的达标片段"
        why = "这轮达到设定门槛的时间较少，下一轮先试一个小目标，不要求全程达标。"
        summary = "从一个小片段开始"
    elif end_lower:
        focus, title = "finish_routine", "到后半段，也记得回到任务"
        why = "后段平均读数低于前段，但这并不能说明原因。下一轮可以试试固定的回到任务步骤。"
        summary = "看看后半段有什么不同"
    elif variable:
        focus, title = "steady_routine", "试着把一个达标片段连得更长"
        why = "这轮读数有起伏，达标出现在多个片段中。先尝试延长其中一个片段，不必追最高读数。"
        summary = "从多个片段中找自己的节奏"
    elif ratio >= .8:
        focus, title = "repeat_success", "用相同设置，再试一次"
        why = "这轮大部分有效时间都达到了门槛。先观察能否重复这次表现，不急着增加难度。"
        summary = "把这次的节奏再试一遍"
    else:
        focus, title = "small_step", "给下一轮一个小目标"
        why = "这轮已经有达标片段，可以从最长的那个片段出发，尝试小幅延长。"
        summary = "从已经做到的片段出发"

    # Small optional challenge; never exceed this round's active duration or change device settings.
    baseline = m["best_streak"]
    ceiling = max(0., math.floor(m["active_seconds"] * 10) / 10)
    if focus == "repeat_success":
        target = min(ceiling, math.floor(baseline * 10) / 10)
    elif focus == "first_steps":
        target = min(ceiling, max(1., min(5., math.floor(baseline) + 1)))
    else:
        target = min(ceiling, math.floor((baseline + min(2., max(1., baseline * .1))) * 10) / 10)
    goal = {"id": focus, "title": title, "metric": "best_streak", "baseline": baseline,
            "target": target, "unit": "seconds", "evidence_ids": ["target"],
            "text": "下一轮保持门槛 %g 和相同预设，试着出现一个至少 %g 秒的连续达标片段（本轮最长 %.1f 秒）。这是可选的小挑战，没达到也没关系。" % (m["reference"], target, baseline),
            "why": why}
    if end_lower and focus == "finish_routine":
        goal["evidence_ids"].append("segments")
    if variable and focus == "steady_routine":
        goal["evidence_ids"].append("level")

    steps = [step("choose_cue", "开始前只选一个简单任务提示，比如看着小车前方或跟随页面指示；这一轮先围绕它练习。", ["target"])]
    if focus == "finish_routine":
        steps.append(step("return_later", "进入后半段时，轻轻提醒自己“回到眼前的任务”；如果发现自己在想别的事，就从当前一步继续。", ["segments"]))
    elif focus == "steady_routine":
        steps.append(step("ignore_fluctuation", "看到读数上下变化时，不急着追数字；继续做刚才选的小任务，再观察下一段。", ["level", "target"]))
    elif focus == "repeat_success":
        steps.append(step("repeat_routine", "回想这轮用了什么任务提示，下一轮先沿用同一种做法和设置，看看记录是否相近。", ["target"]))
    else:
        steps.append(step("return_to_task", "发现自己走神时，可以默念“回来啦”，再看向任务；不用责怪自己，也不用盯着分数。", ["target"]))
    steps.append(step("reflect_after", "结束后告诉老师：哪个时段做起来更轻松，哪里想换个方法。把自己的感受和记录一起看。", ["quality"]))
    encouragement = "你已经有了可以作为起点的达标片段。下一轮只试一个小变化，没达到目标也可以再调整。"
    if baseline == 0:
        encouragement = "这次记录只是一个起点，不是给你的评分。先试一个小任务，按自己的节奏来。"
    elif focus == "repeat_success":
        encouragement = "这轮有不少达标时间，值得为这次尝试点个赞！不必每次都超过自己，按舒服的节奏继续。"
    return {"focus": focus, "summary": summary, "goal": goal, "suggestions": steps,
            "encouragement": encouragement, "display_values": values}

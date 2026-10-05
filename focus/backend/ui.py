"""Tk adapter: commands carry session IDs; refresh only renders backend snapshots."""
import math
import tkinter as tk
from .engine import TERMINAL

REASONS = {"valid": "信号正常", "not_connected": "未连接", "not_worn": "已连接，未佩戴",
           "calibrating": "设备校准中", "calibration_timeout": "设备校准超时，请检查佩戴",
           "stale": "已连接，数据停止更新", "missing_attention": "缺少 Attention",
           "sdk_zero_unverified": "收到零值，SDK 定义待确认", "unverified_identity": "SDK 缺少可靠帧标识",
           "nonfinite_or_nonnumeric": "无效数值", "out_of_range": "数值超范围",
           "not_ready": "指定玩家尚未就绪", "illegal_state": "当前状态不允许此操作",
           "stale_session": "已忽略上一场操作", "countdown_signal_lost": "倒计时中信号丢失，请重新确认",
           "all_signals_lost": "全部信号丢失，本场已中断", "emergency": "急停锁定，请检查原因后复位",
           "duration_complete": "训练完成", "virtual_finish": "已到达虚拟终点", "manual_pause": "已暂停",
           "storage_buffer_timeout": "记录超时，已停止输出", "manual_end": "已结束"}
STATES = {"preparing": "准备", "countdown": "统一倒计时", "running": "进行中", "paused": "已暂停",
          "finished": "本场结束", "aborted": "本场中断"}
COLORS = ("#FF606D", "#549BFF")


def number(value, suffix=""):
    return "暂无足够数据" if value is None else f"{value:.1f}{suffix}"


class SessionPanel:
    def __init__(self, root, backend, activity):
        if backend is None:
            raise RuntimeError("请通过 app.py 启动，界面必须连接后台服务")
        self.root, self.backend, self.activity = root, backend, activity
        self.alive, self.export_future = True, None
        self.export_message = ""
        self.root.title(f"脑控赛车 · {'专注训练' if activity == 'training' else '双人竞速'} · {backend.config.mode}")
        self.root.geometry("1000x660")
        self.root.minsize(780, 530)
        self.root.configure(bg="#07111F")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda event: self.emergency_stop())
        self.header = tk.Label(root, bg="#07111F", fg="#E7F4FF", font=("Microsoft YaHei", 19, "bold"))
        self.header.pack(pady=(12, 4))
        self.notice = tk.Label(root, bg="#07111F", fg="#FFCC77", font=("Microsoft YaHei", 11))
        self.notice.pack()
        self.canvas = tk.Canvas(root, bg="#091726", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=14, pady=8)
        self.options = tk.Frame(root, bg="#07111F")
        self.options.pack()
        self.selection = tk.StringVar(value="60" if activity == "training" else "100")
        tk.Label(self.options, text="下一场时长（秒）" if activity == "training" else "下一场虚拟距离", bg="#07111F", fg="white").pack(side="left")
        choices = ("60", "180", "300") if activity == "training" else ("100", "300", "500")
        tk.OptionMenu(self.options, self.selection, *choices).pack(side="left", padx=6)
        self.controls = tk.Frame(root, bg="#07111F")
        self.controls.pack(pady=8)
        self.buttons = {}
        for key, title, color in (("prepare", "应用设置 / 新一场", "#315673"), ("start", "确认玩家，开始", "#16886C"),
                                  ("pause", "暂停", "#315673"), ("resume", "继续", "#16886C"),
                                  ("end", "结束", "#315673"), ("emergency", "急停 Esc", "#B52C46"),
                                  ("reset", "已排除原因，复位", "#8B4D22"), ("export", "导出", "#315673")):
            button = tk.Button(self.controls, text=title, bg=color, fg="white", relief="flat", padx=9, pady=7)
            button.pack(side="left", padx=3)
            self.buttons[key] = button
        self.storage = tk.Label(root, bg="#07111F", fg="#9CAFBE", font=("Microsoft YaHei", 10))
        self.storage.pack(pady=(0, 10))
        self.refresh()

    def intent(self, action, session_id, **options):
        self.backend.submit_intent(action, session_id=session_id, **options)

    def prepare(self, session_id):
        options = {"duration" if self.activity == "training" else "distance": float(self.selection.get())}
        self.intent("prepare", session_id, **options)
        self.export_message = ""

    def export(self, session_id):
        if self.export_future is None:
            self.export_message = "正在导出…"
            self.export_future = self.backend.export(session_id)

    def emergency_stop(self):
        self.intent("emergency", self.backend.snapshot()["session_id"])

    def on_close(self):
        self.alive = False
        self.intent("end", self.backend.snapshot()["session_id"])
        self.root.destroy()

    def refresh(self):
        if not self.alive:
            return
        state = self.backend.snapshot()
        self.last_snapshot = state
        sid, status = state["session_id"], state["state"]
        mode = "模拟数据" if state["mode"] == "simulation" else "实机采集"
        session_kind = "正式比赛" if self.backend.config.session_kind == "formal" else "体验模式"
        self.header.config(text=f"{mode} · {session_kind} · {len(state['players'])}人 · {STATES[status]} · {state['elapsed']:.1f} 秒")
        reason = state["last_rejection"] or state["reason"]
        title = REASONS.get(reason, reason)
        if status == "countdown":
            title = f"{state['countdown']} · 保持佩戴，两路（单人时一路）必须持续就绪"
        if state["result"]:
            title += " · " + {"tie": "虚拟成绩平局", "player_1": "玩家1先到达虚拟终点", "player_2": "玩家2先到达虚拟终点"}[state["result"]]
        self.notice.config(text=title or "选择下一场设置后应用；确认指定玩家就绪，再点击开始")
        for key, button in self.buttons.items():
            if key == "prepare":
                command = lambda s=sid: self.prepare(s)
                enabled = status in ("preparing", "finished", "aborted") and state["safety"] == "inhibited"
            elif key == "export":
                command = lambda s=sid: self.export(s)
                enabled = state["saved"] and self.export_future is None
            else:
                command = lambda k=key, s=sid: self.intent(k, s, **({"confirmed": True} if k == "reset" else {}))
                enabled = {"start": status == "preparing" and all(p["valid"] for p in state["players"]),
                           "pause": status == "running", "resume": status == "paused" and all(p["valid"] for p in state["players"]),
                           "end": status not in TERMINAL, "emergency": True,
                           "reset": state["safety"] == "emergency_locked"}[key]
            button.config(command=command, state="normal" if enabled else "disabled")
        if self.export_future is not None and self.export_future.done():
            try:
                paths = self.export_future.result()
                self.export_message = "已导出：" + " / ".join(p.name for p in paths)
            except Exception as exc:
                self.export_message = f"导出失败：{exc}"
            self.export_future = None
        health = state["storage"]
        save_text = health["error"] or health["warning"] or ("本场记录已保存" if state["saved"] else "持续记录中，待提交缓冲 %.2f 秒" % health["lag_seconds"])
        self.storage.config(text=(self.export_message or save_text) + " · 成绩与动力均为软件估算", fg="#FF8A80" if health["error"] else "#9CAFBE")
        self.draw(state)
        self.root.after(100, self.refresh)  # Display-only; no control commands or counters.

    def draw(self, state):
        from EEG import draw_two_lane_track, draw_race_car
        canvas = self.canvas
        canvas.delete("all")
        width, height = max(760, canvas.winfo_width()), max(330, canvas.winfo_height())
        count = len(state["players"])
        for i, player in enumerate(state["players"]):
            left, right = 12 + i * (width - 24) / count, 12 + (i + 1) * (width - 24) / count - 10
            canvas.create_rectangle(left, 12, right, 190, fill="#10283C", outline=COLORS[i])
            rows = [f"玩家{i+1} · {REASONS.get(player['reason'], player['reason'])}",
                    f"Attention {number(player['raw']) if isinstance(player['raw'], (int,float)) else '--'}  平滑 {number(player['smoothed'])}  动力 {player['power']*100:.1f}%",
                    f"有效 {player['valid_seconds']:.1f}s   达标 {number(player['stable_ratio'], '%')}   最长连续 {player['best_streak']:.1f}s",
                    f"真实样本 {player['sample_count']}   平均 {number(player['average'])}   趋势 {number(player['trend'])}",
                    f"个人参考 {player['reference']:.0f} · 设备校准 {player['calibration']} · {player['data_status']}"]
            for n, text in enumerate(rows):
                canvas.create_text(left + 12, 34 + n * 31, anchor="w", text=text, fill=COLORS[i] if n == 0 else "#D7E5F1", font=("Microsoft YaHei", 10 if n else 13))
        if self.activity == "racing":
            centers = draw_two_lane_track(canvas, 40, 215, width - 40, height - 35, COLORS)
            for i, player in enumerate(state["players"]):
                x = 80 + (width - 180) * min(1, player["position"] / state["distance"])
                draw_race_car(canvas, x, centers[i], COLORS[i], scale=.45, state="running" if state["state"] == "running" else "paused")
        else:
            left, right, top, bottom = 50, width - 30, 225, height - 28
            for value in (0, 25, 50, 75, 100):
                y = bottom - (bottom - top) * value / 100
                canvas.create_line(left, y, right, y, fill="#234056")
                canvas.create_text(left - 18, y, text=value, fill="#7896AC")
            start = max(0, state["elapsed"] - 60)
            for i, player in enumerate(state["players"]):
                points = []
                previous = None
                for t, raw in player["history"]:
                    if t < start:
                        continue
                    if previous is not None and t - previous > self.backend.config.data_timeout:
                        if len(points) >= 4:
                            canvas.create_line(*points, fill=COLORS[i], width=2)
                        points = []
                    points += [left + (right-left) * (t-start) / 60, bottom-(bottom-top)*raw/100]
                    previous = t
                if len(points) >= 4:
                    canvas.create_line(*points, fill=COLORS[i], width=2)
            canvas.create_text(width/2, height-10, text="最近 60 秒 · 仅真实样本，缺测处断线", fill="#7896AC")

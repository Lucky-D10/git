# 脑电训练与双车竞速

项目有一个明确的启动入口：`app.py`。训练、双人竞速、设备诊断和固定回放都必须显式选择数据来源；程序不会因为实机依赖缺失而偷偷切换到模拟数据。

## 快速开始

电脑演示（不接触 GPIO 或头环）需要主动选择模拟模式：

```bash
python app.py training --mode simulation --players 1
python app.py racing --mode simulation
python app.py replay --mode simulation --output reports/replay.json
```

树莓派实机运行需要 Python 3.9+、`python3-tk`、`python3-rpi.gpio` 和厂商提供且与系统架构及 Python ABI 匹配的 `attention_usb` wheel：

```bash
sudo apt update
sudo apt install python3-tk python3-rpi.gpio python3-venv
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py training --mode hardware --players 1
python app.py racing --mode hardware
```

实机依赖缺失时，启动会逐项显示缺少 `attention_usb` 或 `RPi.GPIO` 的具体原因。请先运行环境检查：

```bash
python app.py training --mode hardware --players 1 --environment
python app.py diagnose --mode hardware
python app.py diagnose --mode hardware --port /dev/ttyACM0 --stream
```

诊断只连接头环，不初始化 GPIO。端口可以写入 `config/hardware.json` 的 `headband_ports`；留空时自动发现，两个设备必须是不同端口。

## 配置和模式

`config/hardware.json` 与 `config/simulation.json` 集中记录端口、BCM 引脚、PWM 频率、动力上下限、数据和控制超时、校准超时、回放随机种子等参数。启动时记录完整配置摘要和 SHA-256，界面标题、日志和报告都保留 `hardware` 或 `simulation` 模式标识。模拟模式使用固定种子，便于重复验收。

本次开发机快照见 [docs/environment-stage2.json](docs/environment-stage2.json)；其中明确列出 Python、SQLite、平台以及未安装的实机依赖。

动力规则为 20 以下停车、25～50% 轨道占空比上限、0.8 秒控制心跳超时；单路失联只停该路，另一车道继续。手动暂停时两路动力归零且暂停时间不计入有效时长；恢复必须经过状态检查和倒计时。急停会锁定输出，排除原因并人工确认后才能重新开始。体验模式双路失联仍可继续计时，正式比赛双路失联会中断本场。报告明确区分虚拟赛程成绩和传感器 Attention 读数。

完整规则表见 [docs/product-rules.md](docs/product-rules.md)，模块边界见 [docs/module-plan.md](docs/module-plan.md)。

## 固定回放

`replay.py` 提供稳定输入、高低交替、单路/双路断连、校准未完成、重复样本、暂停恢复和急停旧回调等固定场景；`replay_samples.json` 是可读的最小样本。相同 Python 版本和配置下，回放输出逐次一致：

```bash
python app.py replay --mode simulation
python app.py replay --mode simulation --database data/focus.sqlite3 --session-id <session-id>
python app.py web --mode simulation
```

## 第二阶段后台与数据记录

`backend/engine.py` 是不依赖 Tk 的训练/竞速状态机；`backend/service.py` 按独立控制周期接收设备帧、处理操作意图、更新计时和输出快照。`app.py` 启动界面时由后台服务负责算法和动力输出，页面只提交开始、暂停、继续、结束和急停意图。设备采样、控制周期和页面刷新分别运行，旧会话 ID 的操作会被拒绝。

`backend/storage.py` 使用独立 SQLite 写入线程，启用 WAL、`synchronous=FULL` 和事务批量提交。数据库包含玩家、会话、参与者、配置快照、逐路样本、事件、统计和报告状态；未完成会话在下次启动时标为 `process_restart`。样本保存原始时间、相对时间、序号、连接代次、有效性和缺测原因，导出采用长表，双方不会按第 N 行强行对齐。报告在记录未完整提交或写入故障时不会标记为完整。

后台状态、转换前置条件、三种时间尺度、样本口径、恢复策略和现场验收清单见 [docs/stage2-backend.md](docs/stage2-backend.md)。两个 Tk 文件现在是共享后台面板的启动壳；改造期间的原始大界面保存在 `backups/`，便于回退。

第三阶段 Web 应用已通过本机 HTTP/WebSocket 和 800×480 浏览器流程验证。运行 `.venv/Scripts/python app.py web --mode simulation`，访问 `http://127.0.0.1:8000`；先点击“成为操作端”，再准备并开始。官方 ECharts 资源全部本地化。接口、安装、systemd/kiosk、维护和回退说明见 [docs/stage3-web.md](docs/stage3-web.md)，实际验收范围见 [docs/stage3-validation.md](docs/stage3-validation.md)。

## 测试

```bash
python -m unittest discover -v
python -m py_compile app.py settings.py session.py diagnostics.py replay.py EEG.py "Focus Training.py" "Focus Racing.py"
```

测试覆盖快照生命周期、重复样本、动力与看门狗、单双路失联、暂停/急停、报告边界、入口文件名和固定回放。当前开发机没有头环 SDK 或 GPIO，真实轨道仍需现场空载、低专注停车、单路断连、急停、退出清理、磁盘满和断电恢复验收。

## 代码边界

- `EEG.py`：设备采集适配、GPIO 看门狗和兼容性的旧报告组件；业务状态由 `backend/` 持有。
- `settings.py`：配置校验、模式和配置摘要。
- `backend/engine.py`：设备/会话/安全状态、计时、统计和竞速积分。
- `backend/service.py`：控制调度、意图队列、输出所有权和异步落盘边界。
- `backend/storage.py`：SQLite 事务、恢复、导出和报告完整性。
- `diagnostics.py`：只读设备诊断。
- `replay.py`：固定回放输入与结果。
- `Focus Training.py`、`Focus Racing.py`：只负责 Tk 展示和操作意图，业务由 `backend/` 提供。
- `web/`：FastAPI 接口、WebSocket 快照、控制租约和 800×480 本地页面。

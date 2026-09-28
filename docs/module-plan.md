# 模块拆分方案

| 模块 | 当前边界 | 后续迁移目标 |
|---|---|---|
| 设备接入 | `EEG.py` 的 SDK 发现、连接、快照和重连 | `EEG.attach_frame_sink`，只向后台投递不可变帧 |
| 数据处理 | `backend/engine.py` 的范围检查、去重、平滑和统计 | 后续可独立为 `signal_processing.py` |
| 会话管理 | `backend/engine.py` 的状态机和 `backend/service.py` 的意图队列 | 同一状态机供 Tk/Web 使用 |
| 控制与保护 | `backend/hardware.py`、`EEG.py` GPIO 初始化和急停 | 后台单一输出所有者 |
| 数据存储 | `backend/storage.py` SQLite 异步事务 | 事件、样本、统计和配置同一会话保存 |
| 统计与报告 | `backend/engine.py` 基础统计、`backend/storage.py` 导出 | AI 报告作为独立异步任务 |
| 界面适配 | `backend/ui.py` 与两个 Tk 壳文件 | Tk 和 Web 都使用统一快照/意图契约 |
| Web 接口 | `web/app.py`、`web/runtime.py` 和 `web/static/` | FastAPI 普通请求、WebSocket 快照、单操作端租约和本地 kiosk 页面 |

第二阶段已把训练/竞速状态、计时、统计和控制移出页面；Tk 入口只渲染后台快照并发送带会话 ID 的操作意图。

# 阶段三：本机 Web 应用、部署与验收

## 电脑运行

使用虚拟环境，避免把“系统 Python 缺包”误认为项目无法运行：

~~~powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python app.py web --mode simulation
~~~

打开 http://127.0.0.1:8000 。训练人数在首页选择训练后的独立步骤中选择；Web 进程采集两个设备槽位，单人会话只统计绑定的一路，另一车道动力为零。也可用 --web-port 8765 换端口。--port 专供串口诊断。新版界面说明见 [youth-ui-v2.md](youth-ui-v2.md)。

首页选择活动并请求操作权限 → 选择人数和昵称 → 头环准备 → 确认就绪开始 → 实时训练 → 暂停/继续 → 结束确认 → 本次收获 → 详细数据 → 下载 JSON/CSV。竞速在首页选择“小车竞速”，两路就绪后统一倒计时；进度与胜负由后台决定。老师设置中的预设仅对下一场生效。

运行模式始终显示在页面、数据库、报告和日志中。实机依赖缺失会列出具体原因，不切换模拟。FastAPI 0.115.12、Uvicorn 0.34.2、WebSockets 15.0.1 为本次验证版本；完整开发环境记录见 environment-stage3.json 和 development-web-lock.txt。后者是 Windows 环境清单，不能作为树莓派硬件 SDK 的版本证明。

## 页面和图表

- 首页：训练、竞速、当前会话入口、成长记录与老师设置。
- 准备：选择单/双人和昵称，分路检查连接、佩戴、校准、新信号及未就绪原因。时长、目标、规则和绑定移到老师设置/维护页。
- 实时页：平滑读数仪表盘、目标、当前连续达标、短曲线；双人左右对称；竞速显示 SVG 双车道、虚拟进度与动力等级。
- 报告：简洁的本次收获，以及独立的详情页。详情可切换玩家查看原始/平滑值、平均值、达标比例、全程曲线、目标与异常位置、有效时间分布和逐路导出。未提交完显示保存中，中断记录不冒充完整报告。
- 历史：玩家、UTC 日期和同条件筛选。对比条件哈希包含模式、规则、人数、目标、动力参数、算法、时长/距离和绑定。只有选定同条件组才画该玩家最长连续达标时间趋势。
- 维护：采集状态、存储健康、配置/版本、日志 ZIP、释放控制权和退出训练。维护退出结束会话、释放租约；随后 Alt+F4 返回桌面，不自动重新打开 kiosk。

官方 ECharts 5.6.0 已存于 web/static/，许可证、NOTICE、来源和 SHA256 同目录。浏览器运行时没有 CDN、在线字体或其他外部资源。图表实例只创建一次，后续 setOption 更新，不随快照销毁。原始/平滑值来自不同数据字段，缺测与暂停插入 null，connectNulls=false。全程图支持缩放、目标线和异常位置；报告事件列表给出文字原因，避免只看颜色。

完整记录参与区间时长统计，按有效期、运行状态、断连及暂停切分。绘图超过约 1600 点时按窗口保留极值/端点/缺测标记；抽稀不改变统计。实时显示最多保留每路 600 个显示点。玩家 1 统一蓝色、玩家 2 橙色，同时用编号和不同符号标识。已按 800×480 无头浏览器检查，可纵向滚动查看完整报告/配置；触摸按钮最小高度 44 px。

图表更新依据 [ECharts 官方动态数据说明](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)，通信依据 [FastAPI WebSocket 文档](https://fastapi.tiangolo.com/advanced/websockets/)。

## 通信和控制权限

HTTP 控制：POST /api/session/{sid}/action，含 action、request_id、token 和本次选项。返回的是后台控制线程决定后的收据，不是“成功入队”。prepare/start/pause/resume/end/emergency/reset 为唯一外部操作；外部请求不能调用 fault 等内部事件。

幂等键为 (租约 token, request_id)。同键同请求返回相同结果，同键不同内容返回 idempotency_conflict。结果超时返回 202 result_pending_retry_same_id；前端保留原请求编号并禁用新的普通操作，重试按钮查询原操作。急停有独立请求与优先队列，仍然可用。旧 sid 不能作用于新场。缓存有界为 1024 条；达到本租约操作上限后须释放重新领取，结束/急停仍可使用。失效 token 不能重新执行已淘汰操作。请求端取消等待不会取消后台 Future 导致控制线程异常。

只读 GET /api/session、GET /api/sessions、GET /api/sessions/{sid}/report 不创建会话。刷新重读快照，保留后台的实际计时和状态。

WS /ws 先返回独立 connection ID，再每约 100 ms 发送最新快照与最近事件；每客户端只发送最新状态，不排队积压旧快照。快照携带设备事实、动力、时间、进度、绑定和记录健康。

- 通过 POST /api/control/claim 以 connection ID 显式领取权限；同一时间仅一个连接拥有租约。
- token 仅在当前页面内存中，其他标签页不能通过 localStorage 继承权限。
- 控制心跳只接受该连接上的 WebSocket 消息，当前页面每 300 ms 发送，默认 2 s 过期。只读观看不续约。
- 连接断开立刻撤销对应租约；半断线在过期后由独立控制线程暂停、动力归零。即使重新领取发生在下个控制步前，也会识别所有者代次变化并暂停。
- 重连不会恢复动力。刷新也会失去操作权，重新领取后必须手动继续并通过倒计时。
- 前端超过 700 ms 没有新快照立即禁用控制。后台浏览器心跳与 0.8 s 的电机命令看门狗相互独立。
- 初版命令行只接受 127.0.0.1/localhost；HTTP 检查 loopback 来源、Host、Origin 和 X-Focus-Client，WS 检查 Origin。未开放局域网，不提供“裸绑定 0.0.0.0”的开关。未来局域网部署需独立凭证、HTTPS 和权限设计。

导出通过后台执行器，下载路径限制在持久目录 exports 中。维护日志导出不打包数据库或完整样本。数据库查询在 API 工作线程运行，不进入控制循环。

## 树莓派安装

以下命令只在目标树莓派上执行；本次 Windows 开发环境没有执行安装服务、GPIO 或桌面配置。目标系统应已安装桌面和 Chromium；实际 SDK wheel 必须与 Python ABI/架构匹配。Pi 型号、系统、SDK 版本和 GPIO 可用性必须记录现场环境报告。

采用 /opt/focus/releases/<版本>、/opt/focus/current 符号链接、/etc/focus/hardware.json、/var/lib/focus 三处独立管理应用、配置和持久数据。以已创建的 focus 专用桌面账户为例：

~~~bash
sudo apt install python3-venv python3-tk python3-rpi.gpio chromium curl
sudo useradd -m -s /bin/bash focus  # 仅账户不存在时执行
sudo usermod -aG gpio,dialout focus
sudo mkdir -p /opt/focus/releases/stage3-v1 /etc/focus
# 将本次源代码复制到 /opt/focus/releases/stage3-v1；不复制 Windows .venv/data/reports。
cd /opt/focus/releases/stage3-v1
sudo python3 -m venv --system-site-packages .venv
sudo .venv/bin/python -m pip install -r requirements.txt
# sudo .venv/bin/python -m pip install /path/to/vendor_attention_usb_<实际版本>.whl
sudo cp config/hardware.json /etc/focus/hardware.json
sudo ln -s /opt/focus/releases/stage3-v1 /opt/focus/current  # 初装；升级/回退见下文
sudo cp deploy/focus-web.service /etc/systemd/system/
~~~

编辑 /etc/focus/hardware.json：storage_path 必须为 /var/lib/focus/focus.sqlite3；headband_ports 优先使用两个稳定且不同的 /dev/serial/by-id/... 路径，头环 1/2 对应这个数组的顺序。确认引脚、动力上限、阈值和超时。配置设 root:focus、0640；应用文件由管理员持有，focus 只需读取。

~~~bash
sudo chown root:focus /etc/focus/hardware.json
sudo chmod 640 /etc/focus/hardware.json
sudo systemctl daemon-reload
sudo systemctl enable --now focus-web
curl --fail http://127.0.0.1:8000/api/health
journalctl -u focus-web -n 100 --no-pager
~~~

systemd 使用 focus 账户及 gpio/dialout 组；不依赖联网，multi-user 阶段启动。StateDirectory 为 /var/lib/focus；应用只读，记录目录可写。启动与异常重启均创建准备态，动力禁止输出。启动失败不打开自动模拟。服务 SIGINT 正常停止会结束记录并急停；无法处理信号、掉电或系统完全失效时的实体动力撤销仍需硬件保护与现场验证。

## 图形会话与开机等待

在实际桌面环境选择一种启动方式，不要两种同时配置：

- 当前 Raspberry Pi OS 的 labwc：按 deploy/labwc-autostart.txt 向专用桌面账户 ~/.config/labwc/autostart **追加**命令，保留原文件。桌面自动登录可通过系统配置工具设置。
- 支持 XDG autostart 的桌面：复制 deploy/focus-kiosk.desktop 到 ~/.config/autostart/。

deploy/kiosk.sh 使用独立的标准库等待服务 kiosk_boot.py（仅 127.0.0.1:8001），先展示“正在连接后台/重试”，轮询 8000 的健康检查，服务可用后跳到首页。无需外网；后台未启动也能显示等待页。正常退出 Chromium 会停止等待辅助进程并回到桌面。Chromium 命令名自动查找 chromium 或 chromium-browser。

labwc 配置依据 [树莓派官方 kiosk 指南](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/)。本仓库采用单页面与独立健康检查，不使用指南中的多网站轮播。

## 维护与回退

- 网页维护页可导出 focus-logs.zip；后台运行时不另开头环串口。
- 命令行：sh deploy/focus-maintenance.sh status|logs|export；stop/restart 通过 sudo 执行。数据库默认每次启动保留最近 5 个 SQLite 备份，日志 2 MiB × 5 轮换。
- 独立诊断：先 sudo systemctl stop focus-web，再使用 app.py diagnose --mode hardware --port <实际端口>；结束后重启服务。
- 发布新版本：建立新 release 和它自己的 .venv，验证依赖；停止后台，备份配置/数据库，再切换 current 链接，最后启动。不要覆盖持久数据。
- 回退：sudo sh deploy/rollback.sh /opt/focus/releases/<上一已验证版本>。脚本检查目标边界，停止服务，使用 SQLite backup API 备份数据库和配置到 /var/lib/focus/rollback，再原子切换 current。只回退支持当前配置/数据库版本的已验证 release；若旧版本配置字段不兼容，由维护人员在停止服务期间从对应备份恢复配置。本阶段没有破坏性数据库迁移，脚本不删除会话或自动回滚记录。
- 服务恢复只负责程序，实体硬件撤销动力不能依赖 systemd 自动重启。

## 重复验收

~~~powershell
.venv/Scripts/python -m unittest discover -v
.venv/Scripts/python -m compileall -q app.py backend web deploy tests
~~~

HTTP/WS 集成测试用临时 SQLite 和真实控制线程；无 FastAPI 的环境会明确跳过集成测试，因此须使用已安装 requirements-dev.txt 的 .venv 才能完整验收。

浏览器验证需要 Node + Playwright（package.json）。先启动模拟服务；FOCUS_URL 默认 http://127.0.0.1:8765，BROWSER_PATH 可指向已安装 Chromium/Edge。运行 npm run test:browser，结果和 800×480 截图写入 reports/stage3。测试拒绝外域资源；涵盖训练、竞速、表单保持、暂停恢复、读者页面、主动断线、刷新不重建、报告和导出。

持续测试 npm run test:soak 默认 7200 秒，FOCUS_SECONDS 可用于短测；脚本仅允许运行 simulation 模式，记录堆内存、DOM 数量、图表实例数、健康请求耗时和延迟。不能把 Windows 短测结果当成 Pi 两小时验收。两小时判定须分析预热后的内存趋势、GC 波动和接口响应；脚本保存数据，不替人宣称不存在泄漏。

API /api/maintenance/metrics?since=<单调时间> 统计最后最多 2000 个显示确认。后台给每次推送附 packet_id，浏览器仅对首次显示的真实新样本在 requestAnimationFrame 后确认。服务端用自己的单调时钟测量“采集适配器接收 → 浏览器一帧更新 → 确认返回服务端”的耗时，因此是显示耗时的保守上界，包含返程开销。不是头环固有延迟，也不等价于光学测得的屏幕像素响应。

现场冷启动：每次真实断电重启并确认 kiosk 可操作后，运行 python tools/record_pi_boot.py --ui-confirmed；Linux boot_id 保证一轮启动只计一次。默认追加 /var/lib/focus/cold-starts.jsonl，必须连续 20 次通过。它不会把进程重启当冷启动。

本次证据见 stage3-validation.md。待目标机实测：20 次冷启动、断外网完整训练/保存/历史、连续 2 小时、实际触摸操作、GPIO 失联/掉电，以及样本显示 p95 < 300 ms 的调优目标。


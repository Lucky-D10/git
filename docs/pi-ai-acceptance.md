# 树莓派 AI 验收入口（2026-10-07）

本次 focus 拷贝目录包含当前运行代码：访客隔离、单次本地统计、学生小目标与建议、DeepSeek 异步报告。此前“一屏小挑战”仍是设计稿，见 docs/design/one-screen-challenge.md，尚未替换运行页面。

公开包不包含真实密钥；文件名带 `-private` 的私人包包含已配置的隐藏文件 `.env.deepseek`，仅供自己的设备使用，不要公开分享。两种包均不包含 Windows .venv、开发数据库、日志或备份。请保留树莓派已有 data、.venv、硬件配置与 /etc/focus/ai.env。不要把旧 focus 删除后覆盖；建议先备份旧目录或按现有 release 方式升级。

本版普通 `app.py` 启动入口会自动读取它所在项目目录的 `.env.deepseek`，无需每次 export，也无需改用专用启动器。路径不依赖终端当前目录，适用于从其他 WorkingDirectory 启动的服务。系统环境变量（包括 systemd 的 `/etc/focus/ai.env`）优先；若旧环境显式设置了 disabled、旧密钥或旧模型，需要先更新对应配置。

## 直接从 focus 文件夹验收

在树莓派终端进入实际复制的目录，例如 `cd ~/focus`。以下命令均以该目录为当前工作目录。若已有 focus-web 服务，请先结束正在进行的体验，再停止服务，避免两个程序同时打开头环、GPIO 或数据库：

```bash
sudo systemctl stop focus-web
```

没有安装该服务时跳过此命令。

### 安装依赖与检查代码

已有树莓派 .venv 时直接使用；没有时先运行 `python3 -m venv --system-site-packages .venv`。不要复制 Windows 的 .venv。

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

实际硬件需要系统 GPIO/Tk 包及匹配当前架构与 Python 版本的 attention_usb 厂商 wheel，安装方法见 README.md。同步代码不能代替 SDK 安装。

### 配置 AI

使用私人包时，解压后确认隐藏文件 `.env.deepseek` 在 `app.py` 旁边，执行 `chmod 600 .env.deepseek` 即可跳过手动填写。运行用户必须能读取它；若由 systemd 的 focus 用户运行，文件应归该用户所有，例如 `sudo chown focus:focus /opt/focus/current/.env.deepseek`（按实际安装路径修改）。已有 /etc/focus/ai.env 时检查其中是否存在需要更新的旧 AI 配置。使用公开包首次配置时创建当前目录的 .env.deepseek：

```bash
touch .env.deepseek
chmod 600 .env.deepseek
nano .env.deepseek
```

填写下面的配置，把占位文字换成本机密钥。不写 export，不把密钥写进命令行或发到聊天中：

```ini
FOCUS_AI_PROVIDER=deepseek
FOCUS_AI_MODEL=deepseek-flash
DEEPSEEK_API_KEY=在此填写密钥
FOCUS_AI_BASE_URL=https://api.deepseek.com
FOCUS_AI_TIMEOUT=15
FOCUS_AI_ALLOW_SIMULATION=0
```

本地加载检查不会请求云端：

```bash
.venv/bin/python tools/check_ai.py --env-file .env.deepseek
```

合成数据联通检查会调用模型并消耗 API 额度；内容校验失败时会附带规则提示重试一次，每次检查最多两次请求。不读取访客数据库，不连接头环或 GPIO。显式 --live 表示允许该次模拟请求，不受运行服务的模拟开关影响：

```bash
.venv/bin/python tools/check_ai.py --env-file .env.deepseek --live
```

若输出 enabled=false，先检查配置；provider_http_401/403 检查密钥或权限；provider_http_402 检查账户额度；provider_unavailable 检查网络、限流与服务状态；unsupported_claim 等校验错误表示调用返回了内容，但未通过报告限制，需要保留模板并复查输出质量。

遇到 `unsupported_claim` 时，新版检查脚本会显示 `Validation field=...; rule=...`，只输出字段和规则，不输出学生记录、模型原文或密钥。后台报告也会在第一次内容校验失败后附带规则提示重试一次，和网络重试共用每任务最多两次请求的额度；再次失败仍保留本地报告。已有失败报告需点击“重试 AI 解读”。树莓派若使用系统 Python，可将本文命令中的 `.venv/bin/python` 换成已装好项目依赖的 `python`。

### 先验证模拟完整流程

```bash
.venv/bin/python tools/start_deepseek.py --mode simulation --allow-simulation
```

在树莓派浏览器打开 http://127.0.0.1:8000。完成至少 30 秒的新体验，进入详细数据，应先有本地反馈，之后显示 AI 解读。模拟调用会消耗额度。确认完毕按 Ctrl+C 正常停止。

### 再验证硬件

先按实际接线核对 config/hardware.json 中串口、BCM 引脚和动力限制；本拷贝目录中的配置只是项目默认值。保留现场配置优先，不盲目覆盖。停止其他采集进程后执行：

```bash
.venv/bin/python app.py web --mode hardware --config config/hardware.json --environment
.venv/bin/python app.py web --mode hardware --config config/hardware.json
```

--environment 只输出环境，不证明设备能连接。启动后仍需人为佩戴、确认与开始。完整记录资格为正常结束、有效时长至少 10 秒、覆盖率至少 80%、至少两个有效样本；短记录不调用 AI。

启动终端应显示 `AI reports: enabled=True provider=deepseek`。完成一轮新的实机体验，正常结束后进入详细数据：先显示本地统计，再由后台自动调用 DeepSeek 并更新 AI 解读、目标、方法和鼓励，无需手动点击生成。断网、额度不足或输出校验失败会保留本地报告；旧报告不会因重启自动重新调用。

## 已经采用 systemd /opt/focus/current 部署

按 docs/stage3-web.md 的新 release 流程更新代码和 Linux 虚拟环境，保留 /etc/focus/hardware.json、/var/lib/focus 数据与原密钥。不要只复制到 ~/focus 后继续使用指向旧代码的服务。

```bash
sudo systemctl cat focus-web
sudo systemctl show focus-web -p ExecStart -p WorkingDirectory -p EnvironmentFiles
```

确认实际指向更新后的代码，服务包含 `EnvironmentFile=-/etc/focus/ai.env` 和 `TimeoutStopSec=45`。检查现有密钥配置（只输出是否存在，不输出密钥值）：

```bash
sudo /opt/focus/current/.venv/bin/python /opt/focus/current/tools/check_ai.py --env-file /etc/focus/ai.env
sudo /opt/focus/current/.venv/bin/python /opt/focus/current/tools/check_ai.py --env-file /etc/focus/ai.env --live
sudo systemctl daemon-reload
sudo systemctl restart focus-web
sudo systemctl status focus-web --no-pager
sudo journalctl -u focus-web -n 80 --no-pager
```

`/etc/focus/ai.env` 由 systemd 注入环境，优先于项目 `.env.deepseek`；两份文件不会互相改写。如果只使用私人包配置，确保旧服务环境未覆盖它，并确保 focus 用户可读取文件。可在项目目录用 `.venv/bin/python tools/check_ai.py --live` 检查默认加载路径；此命令不代表 systemd 的实际环境，服务配置仍以启动日志为准。

## 本轮验收记录

依次记录是否通过：

- AI 合成请求成功；新体验报告出现解读、小目标、方法与鼓励；数字来自本轮记录。
- 单人续玩保留到访并允许同条件对照；换下一位后旧报告和导出不可访问。
- 双人两路数据、目标与反馈没有串人。
- 暂停/恢复、急停、结束的输出行为保持原规则，AI 排队不阻塞控制。
- 断网、无效密钥或输出校验失败时仍能看本地反馈，不丢基础记录。
- 数据不足不评价能力；模拟记录有模拟标记；既有旧缓存不会自动变成新版。
- 800×480 触控、真实头环信号、GPIO 和现场持续运行由树莓派现场确认。

结束验收后关闭模拟调用开关；如使用临时前台进程，停止它后再恢复正式服务。不要把本机打包通过当成树莓派验收已经通过。

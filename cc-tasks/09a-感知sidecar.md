# CC-09a · meta 感知 sidecar（进程 / 识屏 / 活动）（待办 4）

> 移植老桌宠感知逻辑，做成 Python sidecar，上报后端已就绪的 `/sensor/realtime`。
> 【前端仓 Emerald-client/sensor-service/】（Python）+ 【后端 qq-st-bot】补一个 prompt 注入层。
> 参考 `_achive-Emeral-not/sense/*` 与该仓 `速览指南.md`（尤其"代理坑"）。先读 `cc-tasks/audit-老桌宠meta功能.md`。

## 现状（已核对）
- 后端 `POST /sensor/realtime` 已能收 `input{keystrokes:int}` + `screen{package_name, app_label, window_title, visible_text[], clickable_text[]}`（`admin/routers/sensor.py`）。
- `Emerald-client/sensor-service/`（sense/behavior/agent/garden/bot_client）**目录全空**。
- 老桌宠现成可搬：`sense/process_monitor.py`(psutil 进程)、`sense/screen.py`(GLM-4V 识屏 + `_SENSITIVE_KEYWORDS` 敏感词跳过 + win32gui 前台标题)、`sense/activity_tracker.py`(活动分段)。
- ⚠ **关键缺口**：`/sensor/realtime` 数据**当前没有注入 reality prompt**（`prompt_builder` 只注入 activity_snapshot 层 2.6），所以光上报、叶瑄"感知"不到。本任务要补注入层。

## 实现

### 【sidecar】1. 建 `Emerald-client/sensor-service/`
```
sensor-service/
  sense/process_monitor.py   ← 照搬老桌宠（psutil，LEISURE_PATTERNS）
  sense/screen.py            ← 照搬（截屏→GLM-4V→类别/相关/描述；保留 _SENSITIVE_KEYWORDS 跳过；win32gui 前台标题）
  sense/activity_tracker.py  ← 照搬（ActivitySegment 分段）
  bot_client/post.py         ← 新：POST /sensor/realtime（Bearer 鉴权 + 绕系统代理：requests proxies={"http":None,"https":None}）
  config.yaml                ← 采集间隔、各 sensor 开关、后端地址、GLM key
  main.py                    ← 起三个 sensor，按间隔采集→组装 payload→post
  requirements.txt           ← psutil, requests, pillow, pywin32（screen 用）
```
- **隐私红线（必须保留并加强）**：
  - `screen.py` 命中前台标题敏感词（密码/银行/支付/私聊…）→ 跳过识别，不截不传。一定保留。
  - 识屏默认 `enabled:false`（config），由用户显式开；进程监视可默认开（只读进程名，较轻）。
- payload 对齐后端 `/sensor/realtime` 字段名（`input` / `screen.{package_name,app_label,window_title,visible_text,clickable_text}`）。
- 启动方式：随桌宠启动的独立进程（或 Tauri sidecar）。先做"手动 `python main.py`"可用，集成启动作为后续。

### 【后端】2. 补感知注入层 `core/prompt_builder.py`
- 加一个 `mode="tagged"` 的层（如 `3.7_screen_awareness`），从 `/sensor/realtime` 的存储读最新 snapshot，当**话题相关**或**最近 N 分钟有更新**时，注入一句"用户此刻在用 {app_label}/{window_title}，大致在做 {category}"。
  - 照现有 tagged 层写法（参考层 3.5/3.6 的 `_tags & _triggers` 模式）。要带 `_layer` 字段（否则裁剪逻辑看不到）。
  - **只注摘要，不灌敏感原文**；敏感窗口已在采集端跳过，这里再兜一层。
- 确认 `/sensor/realtime` 的读路径（`admin/routers/sensor.py` 的 store），prompt_builder 直接读同一存储。
- 改了注入/tag 相关后按 `AGENTS.md` 跑 `python tests/run_eval.py`。

### 3. 键盘内容级监视（模糊信号版，已定）
- 不做原文 keylogger。`input` 扩展一个模糊字段，如 `input.edit_hint ∈ {"typing_long","editing","deleting","idle"}`（由 sidecar 根据按键频率/退格比例粗判），**不传具体词**。
- 同样吃敏感窗口跳过；后端短 TTL，不进长期记忆。
- prompt 注入层可据此给"她好像在认真写东西/在反复改"这类氛围感知。

## 验收
- sidecar 跑起来后，`/sensor/realtime` 能收到进程/前台/（开启时）识屏数据。
- 敏感窗口（如打开银行页/密码框）→ 不采集不上报（验证跳过生效）。
- 叶瑄的现实回复能体现"知道你在用什么/在做什么"（prompt 注入层生效），且话题无关时不滥注入。
- 识屏默认关；键盘只给模糊信号、无原文。
- `tests/run_eval.py` 通过。

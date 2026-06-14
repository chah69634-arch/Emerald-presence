# 审计 · 老桌宠 meta 功能可用性

> 老桌宠：`D:\ai\_achive-Emeral-not`（= 旧 `Emerald-desktop`），**Python + PyQt6 + Windows API**（win32gui / pygetwindow / pyautogui / psutil / sounddevice / GLM-4V）。
> 新客户端：`Emerald-client`，**Tauri（Rust + React）**。
> **关键发现**：新客户端的 `sensor-service/` 目录是空壳，但其子目录 `sense / behavior / agent / garden / bot_client` **与老桌宠的模块结构一一对应**——架构上明显是预留来把老桌宠这套以 **Python sidecar** 形式移植回来，再通过 HTTP 推给后端 `/sensor/realtime`（该端点已存在）。这就是移植主桥。

---

## 一、功能清单与可移植性

> 「新端现状」对照 `Emerald-client` + `qq-st-bot` 已实现的部分。可移植性分三类：
> **【A 直接复用】** Python 逻辑基本照搬，只换输出（PyQt 信号→HTTP）；
> **【B 转后端工具】** 改写为 `qq-st-bot` 的 `_TOOL_REGISTRY` 工具（含 dangerous 门控）；
> **【C 前端重写】** UI/视觉行为，PyQt 无法复用，需在 Tauri/React 重写。

| # | 功能 | 老桌宠文件 | 做什么 | 依赖 | 新端现状 | 可移植性 | 对应待办 |
|---|---|---|---|---|---|---|---|
| 1 | **后台进程监视** | `sense/process_monitor.py` (75) | 每60s 扫进程，识别 Steam/游戏/视频/微信等「摸鱼」类别 | psutil | ❌ 无（后端 `/sensor/realtime` 能收但没人推） | **A** 极易，纯 psutil 跨平台 | 4 meta监视 |
| 2 | **屏幕识别** | `sense/screen.py` (149) | 每30s 截屏 → GLM-4V 识别内容类别/是否与叶瑄相关/描述；含**敏感词跳过**（密码/银行/支付…）+ 前台窗口标题 | requests, win32gui, GLM-4V | 🟡 后端 `/sensor/realtime` 已能收 screen 字段；客户端采集器空 | **A** 逻辑可复用；win32gui 仅 Windows | 4 识屏（"逻辑已有没打开"） |
| 3 | **活动分段追踪** | `sense/activity_tracker.py` (277) | 把屏幕识别结果聚合成「活动段」，每段只通知一次，检测里程碑/切换 | 纯 Python | ❌ 无 | **A** 纯逻辑，直接搬 | 4 meta监视 |
| 4 | **麦克风音量+语音输入** | `sense/audio.py` (118) | 音量驱动粒子波动；按 Alt 录音→Whisper 转文字发送 | sounddevice, numpy, Whisper | ❌ 无 | **A**(音量)/ 需重接(语音输入入口) | 额外能力（你没列，可选） |
| 5 | **鼠标在场/离开轮询** | `sense/mouse_tracker.py` (33) | 每秒采鼠标坐标，判断在场/移动 | PyQt QCursor | 🟡 新端有 presence/idle 概念 | **C** 前端可直接用 web API | g 桌宠行为 |
| 6 | **蹭鼠标 + 害羞躲避** | `behavior/mouse_interact.py` (86) | 随机间隔触发"蹭"；shy 时窗口推离鼠标；Ctrl 钉住不躲 | PyQt 窗口几何 | ❌ 无 | **C** Tauri 窗口移动重写 | g 桌宠行为 |
| 7 | **病娇弹窗系统** ⭐ | `behavior/yandere.py` (267) | 高活跃且 60min 无互动触发；全屏暗角遮罩 + 连环弹窗「关一弹十」+ 禁交互；ESC 或叶瑄调 `exit_yandere`(写 signal 文件) 退出；台词全走 `send_to_channel` | PyQt 全屏 overlay | ❌ 无 | **C** 前端重写（这正是你要的"系统报错弹窗式找存在感"原型） | g + 4「假报错弹窗说话」 |
| 8 | **离开检测/开机唤醒/每日触发** | `core/lifecycle.py` (179) | 每30s 轮询；away/active 状态机；关机时间记录；开机问候、每日花园检查挂这里 | PyQt timer | 🟡 后端 scheduler 有主动触发；前端无 lifecycle | **A/B** 触发逻辑归后端 scheduler，前端只收 | g 主动行为 |
| 9 | **自主行为循环（agent loop）** | `agent/loop.py` (91) | engagement 低（<0.3「无聊」）时向 `/agent/think` 要一个想法，按返回 JSON 执行桌面动作，最多 MAX_STEPS 步，2h 冷却 | HTTP | 🟡 后端 `/agent/think` 端点存在 | **B** 循环归后端 scheduler/agent | 4 + g |
| 10 | **桌面动作执行器（executor）** ⭐ | `agent/executor.py` (132) | `open_url`(开浏览器) / `launch_netease`+`play_netease_song`(**放歌**) / `play_pause_media` / `minimize_window` / `restore_window` / `send_notification`+`send_important_notification`；**每个动作都有 `config.agent.allow_*` 权限位** | subprocess, webbrowser, pyautogui, pygetwindow | 🟡 新端有 `show_notify`（通知已通）；其余动作无 | **B** 改写为后端 `_TOOL_REGISTRY` dangerous 工具 | **4 危险模式（放歌/开浏览器）核心** |
| 11 | **粒子视觉/情绪** | `visual/particle.py` | set_emotion/set_volume 的粒子系统 | PyQt 绘制 | 🟡 新端有自己的视觉形象 | **C** 已有替代，无需移植 | — |
| 12 | **气泡对话框** | `core/bubble.py` | BubbleWidget 跟随窗口流式显示 | PyQt | ✅ 新端 PetWindow 已有 bubble | 已移植 | g（已搬视觉） |

---

## 二、按你的待办归类（哪些可用 / 怎么用）

### 直接命中「待办 4 · 危险模式」——基本现成，强烈推荐复用其设计
- **executor（#10）+ agent loop（#9）** 是一套完整的「安全开关 + 桌面动作 + 自主触发」方案，且**已有 `allow_*` 权限位**，正是你要的 safe/danger 模式雏形。
- 移植路径 **B**：把 `open_url / play_netease_song / play_pause_media / minimize_window / send_notification` 改写成后端 `core/tools/` 工具，注册进 `_TOOL_REGISTRY`，`dangerous=True` + 走 `agent_control` 权限（后端已有这套门控，见 `docs/security_model.md`）。全局 safe/danger 开关 = 这些工具的总闸。
- 「放歌」当前是写死网易云（`launch_netease`/`play_netease_song`），移植时可保留或泛化为 `play_media`。

### 直接命中「待办 4 · meta 监视 / 识屏」——逻辑可复用
- **process_monitor（#1）+ screen（#2）+ activity_tracker（#3）** 这三个就是「后台进程 + 识屏 + 活动追踪」，且 screen.py **自带敏感词跳过**（密码/银行/支付页面不识别）——这个隐私保护一定要一起搬。
- 移植路径 **A**：作为 **Python sidecar** 跑在 `Emerald-client/sensor-service/`（目录已预留），把结果 POST 到后端已存在的 `/sensor/realtime`。win32gui/前台标题是 Windows-only，可接受（你就是 Windows）。
- 「识屏逻辑已有没打开」的真相：**后端接收端有，老桌宠采集端也有，缺的是把老桌宠这套接到新 sidecar + 默认开关**（config 里 `screen_sensor: false`）。

### 直接命中「待办 g + 4 · 弹窗找存在感」——有现成原型，需前端重写
- **yandere（#7）** 就是你说的「用系统报错弹窗式说话、生气被无视时找存在感」的成熟原型：60min 无互动触发、连环弹窗、台词走情景提示词不硬编码、ESC/工具退出。
- 移植路径 **C**：PyQt 全屏 overlay 无法复用，需在 Tauri 新建一个置顶透明窗 + React 弹窗组件重写；但**触发条件、退出机制、台词走 LLM 的设计可照搬**。「假报错弹窗」样式是新做的皮。

### 「待办 g · 桌宠行为」——锦上添花，前端重写
- mouse_tracker（#5）、mouse_interact（#6 蹭鼠标/害羞躲避）、lifecycle（#8 离开检测/开机唤醒）。视觉行为，PyQt 不能复用，Tauri 重写；lifecycle 的主动触发建议归后端 scheduler。

### 可选 / 已替代
- audio（#4 语音输入）你没在待办里提，作为可选能力记录。
- particle（#11）、bubble（#12）新端已有自己的视觉，无需移植。

---

## 三、可用性结论

| 结论 | 功能 |
|---|---|
| **逻辑可直接复用（A，sidecar）** | 进程监视、屏幕识别（含敏感词保护）、活动追踪、音量 |
| **改写为后端 dangerous 工具（B）** | executor 全套桌面动作、agent loop、lifecycle 触发 |
| **设计可照搬、UI 必须重写（C）** | 病娇弹窗、蹭鼠标/害羞躲避、鼠标在场检测 |
| **已被新端替代，不必移植** | 粒子、气泡、（语音可选） |

**没有任何一个 meta 功能是"不可用/作废"的**——全部要么逻辑可复用，要么设计可照搬。最大成本在 C 类（PyQt→Tauri 的 UI 重写）。

---

## 四、并入施工批次的建议

这份审计直接喂给后续两份 CC 文档（不必单独施工）：

- **`09-meta监视与危险模式.md`（待办 4）** 吸收本审计的 A 类（sensor-service sidecar：进程/识屏/活动 + 敏感词保护）+ B 类（executor→后端 dangerous 工具 + safe/danger 总闸 + agent loop）。建议拆子文档：`09a-sidecar感知`、`09b-危险模式工具与开关`、`09c-玩具文件沙盒`。
- **桌宠行为/弹窗（待办 g）** 单独一份 `11-桌宠行为与存在感弹窗.md`：C 类（yandere 重写为"假报错弹窗"、蹭鼠标/害羞、lifecycle 前端接线）。

> 移植时统一注意：老桌宠台词**全走 `send_to_channel(情景提示词)` 不硬编码**——这条设计哲学要保留，新端所有主动开口同样走后端 LLM，不在前端写死台词。

# CC-09 · meta 监视 + 安全/危险模式（待办 4）— 设计稿

> **这是设计稿，不是施工单。** 先让你过一遍架构与安全边界，确认后再拆 `09a/09b/09c` 三份施工文档。
> 安全敏感，原则：**宁慢勿错**。任何放开系统能力的动作，权限/确认/白名单/审计先到位再开。
> 先读 `docs/security_model.md` + `docs/tools.md` + 老桌宠审计 `cc-tasks/audit-老桌宠meta功能.md`。

---

## 0. 重大现状修正（先看，省得重复造）

审计后发现**待办 4 已经建了一大半**，不是从零开始：

### 危险动作工具——后端基本齐了
`core/tool_dispatcher.py` 已注册并实现：
- `desktop_open_url`（开网页，`action_open_url` 有 URL scheme 白名单）
- `play_song`（**网易云放歌**，自动搜 ID）
- `desktop_play_pause`（媒体播放/暂停）
- `desktop_minimize`（最小化窗口）
- `desktop_notify`（系统通知）
- `device_shutdown` / `device_sleep`（`dangerous=True`，category system）

且已有完整门控：`execute(origin=)` origin 闸门（`_EXECUTE_ALLOWED_ORIGINS={user_live, assistant_intent}`）、`_is_tool_enabled`（`config.tools.<name>.enabled`，默认 True）、`_is_dangerous_tool`、危险确认流（`ask_confirm_text`）。下发链：tool → `_push_desktop_action` → desktop WS（5s ack）→ 失败降级文件队列 `agent_actions()`。

### 客户端动作——部分接了，但有名字错配 bug ⚠️
`Emerald-client/src/shared/api/ws.ts` 的 action 分支处理：`minimize_window` / `open_url` / `show_notify` / `media_play_pause` / `dream_invite`，对应 Tauri `actions.rs` 的 `action_minimize_window/open_url/show_notify/media_play_pause`。
**但后端 `_push_desktop_action` 推的 `type` 是**：`minimize` / `open_url` / `play_pause` / `notify`。
→ **只有 `open_url` 两边对得上**；`minimize≠minimize_window`、`play_pause≠media_play_pause`、`notify≠show_notify` **对不上，这几个动作端到端大概率不通**。`play_song` 客户端无对应 case（需确认它走哪条）。**这是一个现成的接线 bug，必须先修。**

### 感知（meta 监视）——后端就绪，采集端是空壳
- 后端 `admin/routers/sensor.py` 的 `POST /sensor/realtime` 已能收 `input{keystrokes:int}` + `screen{package_name, app_label, window_title, visible_text[], clickable_text[]}`。
- `Emerald-client/sensor-service/`（sense/behavior/agent/garden/bot_client）目录**全空**——采集器没写。
- 老桌宠 `D:\ai\_achive-Emeral-not` 有现成可复用逻辑：`sense/process_monitor.py`(进程)、`sense/screen.py`(GLM-4V 识屏 + **敏感词跳过**)、`sense/activity_tracker.py`(活动分段)。

### 结论
待办 4 拆成四件事，难度重排：
| 事项 | 真实状态 | 难度 |
|---|---|---|
| 危险动作（放歌/开浏览器/通知/最小化） | 工具已建，**修 action 名错配 + 加统一模式开关** | 低 |
| 安全/危险模式总开关 | 不存在，新加（薄层） | 低–中 |
| meta 感知 sidecar（进程/识屏/活动） | 后端就绪，**移植老桌宠逻辑成 Python sidecar** | 中 |
| 键盘输入监视（打了什么/删了什么） | 仅有 keystroke 计数，**细节采集 = 新做 + 隐私敏感** | 中–高 |
| 玩具文件沙盒（只许改几个文件） | 不存在，新加（硬白名单 + safe_write） | 中 |

---

## 1. 安全 / 危险模式 — 设计（→ 施工 09b）

### 模型
在现有"单工具 `enabled` + dangerous 确认"之上，加一个**全局模式**作为总闸：

```
config / runtime:
  meta.mode: "safe" | "danger"   # 默认 safe
```
- **safe 模式**：所有「能影响系统/外部世界」的工具一律拒绝执行——即 category ∈ {desktop, system} 的工具（open_url / play_song / play_pause / minimize / notify / shutdown / sleep / 玩具文件写）。`info`/`memory` 类不受影响。
- **danger 模式**：上述工具按各自的 `tools.<name>.enabled` + dangerous 确认流放行。
- 实现位置：`tool_dispatcher.execute()` 入口加一道 `_mode_gate(tool_name)`：若 mode==safe 且该工具 category 在受限集 → 直接拒绝并返回友好提示（不抛）。**这是唯一新增的硬闸，复用现有 category 字段，改动很小。**
- 切换入口：
  - 后端 `PATCH /system/meta-mode`（Bearer 鉴权）写 runtime；
  - 前端在设置里给一个显眼的「安全 / 危险模式」开关（带说明：危险模式允许叶瑄操作你的电脑）。
- **危险模式不等于无确认**：`device_shutdown` 等 `dangerous=True` 的，即使在 danger 模式仍走确认流。建议把 open_url/play_song 这类"玩具级"留 `dangerous=False`（mode 闸足够），shutdown/sleep 保持 `dangerous=True` 双保险。

### 待你拍板
- (Q1) safe/danger 是**全局一个开关**，还是想要**按工具粒度的白名单**（如 danger 也只允许放歌+开浏览器，不允许 shutdown）？建议：全局开关 + 保留单工具 `enabled` 做细粒度，shutdown 默认 `enabled:false`。
- (Q2) 模式切换要不要**超时自动回 safe**（如开 danger 2 小时后自动收回）？更安全，建议要。

---

## 2. meta 感知 sidecar — 设计（→ 施工 09a）

### 架构
在 `Emerald-client/sensor-service/` 建一个 **Python sidecar**（独立进程，跟桌宠一起启动），移植老桌宠逻辑，输出改为 HTTP POST 后端 `/sensor/realtime`：
```
sensor-service/
  sense/process_monitor.py   ← 照搬老桌宠（psutil，跨平台）
  sense/screen.py            ← 照搬（GLM-4V 识屏 + 敏感词跳过 + 前台标题；Windows win32gui）
  sense/activity_tracker.py  ← 照搬（活动分段）
  bot_client/post.py         ← 新：把结果 POST /sensor/realtime（Bearer 鉴权 + 绕系统代理，见老桌宠速览指南"代理坑"）
  main.py                    ← 调度三个 sensor，按间隔采集→上报
```
- **隐私红线（必须照搬并加强）**：`screen.py` 的 `_SENSITIVE_KEYWORDS`（密码/银行/支付/私聊…）命中前台标题就**跳过识别**，这条一定要保留；识屏默认 `enabled:false`，由用户显式开。
- 后端 `/sensor/realtime` 已就绪，sidecar 只管采集+上报；叶瑄"感知到你在干嘛"= 后端把最新 snapshot 注入现实 prompt（确认 `/sensor/realtime` 的数据有没有喂进 prompt builder，没有则补一个 tagged 层）。

### 键盘输入监视（你的新需求："看在写什么、删了哪些词"）
- 现状只有 `keystrokes:int` 计数。要"看到在写什么 + 撤回删除了哪些词" = 需要**按键内容级采集**，这是**最敏感**的一项。
- 设计建议（隐私优先）：
  - 不做全局 keylogger 式原文留存；改为**聚合信号**：当前活动输入框的"草稿快照差分"（新增/删除的词），且**同样吃敏感词/敏感窗口跳过**（密码框、银行页一律不采）。
  - 默认 `enabled:false`，开启时前端给明确告知。
  - 上报走 `/sensor/realtime` 的 `input` 扩展字段（如 `input.recent_edits:[{added,removed}]`），后端保留极短 TTL、不进长期记忆。
- **(Q3) 这项隐私代价最大，确认要做到什么粒度**：只要"大概在写长文/在删改"的模糊信号，还是要具体词？建议先做模糊信号版。

---

## 3. 玩具文件沙盒 — 设计（→ 施工 09c）

让叶瑄"能改文件"但只限几个玩具文件：
- 新工具 `edit_toy_file`（category desktop 或新 category `toybox`，受 mode 闸约束），参数：`file_key`（枚举，非路径）+ 内容/追加。
- **硬白名单**：后端常量映射 `file_key → 绝对路径`，只含你指定的几个玩具文件（如 `data/toybox/note.txt`、`data/toybox/wishlist.md`）；**绝不接受任意路径**，绝不暴露路径给 LLM。
- 写入走 `core/safe_write.py`（原子写），大小上限，只允许文本。
- 读取同理给 `read_toy_file`。
- **(Q4) 给哪几个玩具文件、放哪个目录？** 建议 `data/toybox/` 下 2–3 个，纯娱乐用途。

---

## 4. 与桌宠"假报错弹窗找存在感"的关系
- "用系统报错弹窗式说话找存在感（生气被无视时）"属于**待办 g + 4 的交叉**，原型是老桌宠 `behavior/yandere.py`。
- 它**不放在 09**（09 是感知+动作+安全），放进 **`11-桌宠行为与存在感弹窗.md`**：那是 UI 行为（Tauri 重写假报错窗 + 触发条件），与本文的"后端工具/感知"分属两层。

---

## 5. 拆分与建议顺序（确认设计后）
1. **09b 安全/危险模式 + 修 action 名错配**（低风险、解锁已建的动作）——**先做**，纯后端 + 一点客户端 ws/前端开关。
2. **09a 感知 sidecar**（进程/识屏/活动，含敏感词保护）——中等，移植老桌宠。
3. **09c 玩具文件沙盒**——中等，独立。
4. 键盘内容级监视——**最后**，且先做模糊信号版，隐私确认后再深入。

> 这四件里 **09b（后端为主）** 与 **09a（sidecar 独立进程）** 互不冲突，可并行；09c 独立。

---

## 待你回答（汇总）
- Q1 安全/危险：全局开关 + 单工具 enabled 细粒度（建议）？还是要别的粒度？
- Q2 danger 模式要不要超时自动回 safe？（建议要）
- Q3 键盘监视粒度：模糊信号（建议）还是具体词？
- Q4 玩具文件：给哪几个、放 `data/toybox/`？
- 另：是否同意"危险动作工具留 dangerous=False 靠 mode 闸，仅 shutdown/sleep 保持 dangerous=True"？

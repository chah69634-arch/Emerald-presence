# 前端活动/梦境 四项修复任务

> 两个仓库：
> - 后端 `D:\ai\qq-st-bot`（Python / FastAPI）
> - 前端 `D:\ai\Emerald-client`（Tauri + React + Rust）
>
> 每个任务自带根因与参照模板，可独立执行。建议顺序：任务1 → 任务3 →（任务4 纯文档无需改）→ 任务2。

---

## 任务1：修复阅读功能 422（最小改动，照抄现成模板）

**现象**：阅读页填入书籍路径，点开始阅读返回 422。

**根因**：前后端协议不匹配。
- 前端 `Emerald-client/src/windows/activity/components/ReadingPage.tsx` 让用户填**文件路径**，调 `readingApi.start(filePath)`。
- Tauri 命令 `Emerald-client/src-tauri/src/lib.rs:1077` `activity_reading_start` 把路径当 JSON 发出：
  ```rust
  activity_post(&app, "/activity/reading/start", json!({ "file_path": file_path }))
  ```
- 但后端 `qq-st-bot/admin/routers/reading.py` 的 `start_reading` 要的是 **multipart 文件上传**（`file: UploadFile = File(...)` + `start_page` / `uid` 的 `Form` 字段）。FastAPI 找不到必填的 `file` 字段 → 返回 422。
- 而且后端要的是文件**字节内容**，前端只传了一个本地路径字符串，根本没读盘。

**修法**：把 `activity_reading_start` 改成「读盘 + multipart 上传」。仓库里已有现成同款实现可照抄——`Emerald-client/src-tauri/src/lib.rs:528` 的 `upload_document`，它就是「读 `file_path` 字节 → `reqwest::multipart::Form` 带 `file` part → POST」。

参照 `upload_document` 改写 `activity_reading_start` 为：
1. `std::fs::read(&file_path)` 读字节；
2. 从路径提取文件名；
3. 构造 `multipart::Form::new().part("file", Part::bytes(bytes).file_name(filename)).text("start_page", "1")`；
4. 用 `http_client()?` + `authorized_request` POST 到 `backend_url(&cfg, "/activity/reading/start")`，带 Bearer token，`.multipart(form)`；
5. 按现有错误处理返回。

> 注意：不要改 `activity_post`（它是 JSON 专用，被其它命令复用）；新写一个 multipart 分支或独立逻辑。

**附带坑（一并处理）**：`ReadingPage.tsx` 输入框 placeholder 写「PDF / TXT」，但后端 `qq-st-bot/core/activity/pdf_reader.py` 的 `extract_pages` 只处理 PDF，TXT 走不通。二选一：
- 后端 `extract_pages` 加 TXT 分支（`.txt` 直接按文本分页）；或
- 前端去掉 placeholder 里的「TXT」字样，只收 PDF。

**验收**：选一个文本型 PDF，填路径 → 开始阅读 → 正常显示页面内容；翻页、关闭正常。

---

## 任务2：国际象棋接入 AI（跨四层，照搬五子棋）

**现状**：`qq-st-bot/admin/routers/chess.py` 开头第 14 行明确「P0 无 AI 对手，不接 Stockfish」。整条链路只有本地双人（start/state/move/legal_moves/close/chat），无 opponent 参数、无 ai_move。chess 引擎用 `python-chess` 库（`requirements.txt` 已有 `python-chess>=1.999`）。

**关键**：五子棋已把 AI 整条链路做完，**逐层照搬**即可。参照映射：

| 层 | 五子棋（已实现，照抄） | 国际象棋（要新增） |
|---|---|---|
| AI 走子器 | `qq-st-bot/core/activity/gomoku_ai.py` → `choose_gomoku_ai_move()` | 新建 `core/activity/chess_ai.py` → `choose_chess_ai_move(board, ai_color, ai_style)` |
| 引擎状态/自动应手 | `core/activity/gomoku.py`（`start_game` 收 opponent/ai_style/ai_player，`make_move` 落子后自动应手，`apply_ai_move`） | `core/activity/chess.py` 加 `opponent`/`ai_player`/`ai_style` 状态 + 落子后自动应手 |
| 路由 | `admin/routers/gomoku.py:184` `/gomoku/ai_move` + start 带 opponent | `admin/routers/chess.py` 加 `/chess/ai_move` + start 加 opponent 参数 |
| Rust 命令 | `Emerald-client/src-tauri/src/lib.rs` `activity_gomoku_ai_move` + start 带 opponent/ai_style | 加 `activity_chess_ai_move` + start 带 opponent；记得在 `invoke_handler` 注册（lib.rs:~1502 列表） |
| 前端 API | `Emerald-client/src/shared/api/activity-api.ts` `gomokuApi.aiMove` + `opponent: 'yexuan_ai'` | `chessApi.aiMove` + start 传 `opponent` |
| 前端 UI | `windows/activity/components/GomokuPage.tsx` | `ChessPage.tsx` 照 GomokuPage 加对手选择 + AI 应手触发 |

**AI 走子器实现建议**：`chess_ai.py` 用 python-chess 的 `board.legal_moves` + 子力评估（material eval）做简单极小化（minimax / alpha-beta，深度 2-3 够用）。`ai_style` 沿用五子棋的 `balanced` / `gentle` / `serious` / `teaching` 四档，影响搜索深度或随机扰动。不引入 Stockfish 外部二进制（与 chess.py 原约束一致，纯 Python 自洽）。

**对手值**：前端用 `opponent: 'yexuan_ai'`，与五子棋保持一致命名。

**验收**：开局选「叶瑄执黑/AI 对手」→ 用户走一步 → AI 自动应手；将军/将死/和棋判定正常；陪伴聊天（chess_chat）正常。

---

## 任务3：动向（Live Feed）三个问题

### 3a 切侧边栏动向被清空 → 保留 8 小时（纯前端）

**根因**：`Emerald-client/src/windows/chat/components/SubFlow.tsx` 的时间轴 `timeline` 存在组件**局部 state**（`const [timeline, setTimeline] = useState<FlowEntry[]>([])`）。切侧边栏任一页 → SubFlow 卸载 → state 销毁，回来显示「暂无记录」。而且硬 `.slice(0, 10)`，没有时间维度。

**修法**：
1. 把 `timeline` 提到组件外的持久存储——模块级单例 store，或并入现有 `StateEngine`（`src/shared/state/store.ts`），或落 `localStorage`（持久化跨重启更稳）。
2. 入轨逻辑保留现有「key 去重」，但保留窗口从 `.slice(0, 10)` 改为按时间过滤：
   ```ts
   const EIGHT_HOURS = 8 * 3600_000;
   timeline.filter(e => Date.now() - e.timestamp < EIGHT_HOURS)
   ```
3. 渲染时也按 8 小时过滤（防止挂载后旧条目残留）。

> 同一份 timeline 数据应在 SubFlow 卸载/重挂后仍存在，这是本任务核心。

### 3b 梦境时动向直接写「在做梦」（后端）

**根因**：动向文案来自 `qq-st-bot/core/activity_manager.py` 的 `get_current()`，它只从 `activity_pool.yaml` 随机抽，完全不知道梦境状态。前端经 `/activity/current`（`admin/routers/activity.py`）拿到。

**修法**：在 `activity_manager.get_current()`（或 `admin/routers/activity.py` 的 `get_activity_state`）里**短路**：先查梦境状态（`core/dream/dream_state.py` 的 `read_state()` / 对应「是否在梦中」判断），若在梦中，直接返回 `current = "在做梦"`，**不调用 `_pick_activity` / `switch_activity`**。

### 3c 共同活动写具体活动（后端）

**根因**：同 `get_current` 不知道有没有正在进行的 reading / gomoku / chess 会话。

**修法**：在短路逻辑里查活跃会话，命中则返回具体文案：
- reading：`core/activity/activity_store.find_active_session(char_id, uid)` → 「在和你一起看《书名》」（用 session.filename）
- gomoku：`core/activity/gomoku.py` `get_active_session(uid, char_id)` → 「在和你下五子棋」
- chess：chess 引擎对应取活跃 session → 「在和你下国际象棋」

**优先级**：`梦境 > 共同活动 > 随机池`。即先判梦境，再判活跃活动会话，都没有才走原来的随机抽取。

**验收**：进入梦境 → 动向显示「在做梦」；开一局五子棋/象棋或一起看书 → 动向显示对应具体活动；都退出后 → 恢复随机活动。

---

## 任务4：「感知边界」「清明模式」是什么（仅说明，无需改代码）

> 此条是查证结论，留作上下文，不用动代码。两者都是进入梦境时冻结进快照的开关，默认值在 `qq-st-bot/core/dream/dream_settings.py` 的 `_DEFAULTS`。

**感知边界 = `boundary_level`**：控制 D5「身体投射」层里**叶瑄能感知到自己身体/生理状态的精细度**。定义在 `core/dream/body_projection.py` 的 `BoundaryLevel`：
- `vague`：单条模糊提示，无分项
- `body_perceptible`（默认）：每轴定性标签，不给数字
- `numbers_visible`：给叶瑄显示数值
- `threshold_break`：数值 + 解除上限（seam，v0 未实现，回退到 numbers_visible）

只管「角色这边看到多少」；用户在 UI 面板永远能看到自己的完整数值（`user_sees_own_numbers` 恒 True），两者正交。还会喂给梦境 HUD 的 `boundary_intrusion`（边界侵入）仪表。

**清明模式 = `lucid_mode`**：两档，控制 D1 自我认知 + D8 导演注记措辞（`core/dream/dream_prompt.py`）：
- `lucid_shared`（默认）：叶瑄知道「这是我们共同的梦」，知道梦醒后现实/关系仍在，可点破是梦
- `non_lucid`：叶瑄沉浸当下，不主动点破「这是梦」

两档下情感底色、说话方式、对她的取向都不变；`/stop` 逃生协议在两档下都强制有效、不受影响。

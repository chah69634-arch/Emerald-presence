# 第二轮：看书 / 棋盘UI / 日记窗口 / 看书文件夹

> 仓库：
> - 后端 `D:\ai\qq-st-bot`（Python / FastAPI）
> - 前端 `D:\ai\Emerald-client`（Tauri v2 + React + Rust）
>
> 任务 A 和 D 强相关（D 做完 A 自动消失），建议合并实现；B、C 独立。

---

## A. 一起看书「无法连接后端」（其实是被掩盖的真实报错）

**关键判断**：任务1 的 multipart 修复已生效（`activity_reading_start` 现在会读盘+上传）。「无法连接后端，请确认后端已启动」**不是真的连不上后端**，而是 `Emerald-client/src/shared/api/activity-api.ts` 里 `parseActivityError` 的**兜底文案**：任何不以 `HTTP ` 开头、又不含反序列化关键词的 Rust 错误，都会被统一显示成这句。

后端 4xx/413 会经 `safe_http_error` 返回 `"HTTP xxx"`（能正常透出）。所以现在这句兜底，真实错误只能是 Rust 命令内部抛的：
- `"读文件失败: {e}"` ← `std::fs::read(&file_path)` 失败（**最可能**：手输路径不存在/反斜杠/带引号/中文路径等）
- `"无法解析文件名"`
- `"上传请求失败"` ← multipart 发送失败

**结论**：大概率是手输文件路径读盘失败，被兜底文案掩盖了。

**两种修法**：
1. **临时快修**：改 `parseActivityError`，让非 HTTP 的 Rust 错误原样透出（而不是一律「无法连接后端」），这样能立刻看到「读文件失败: ...」真因。
2. **根治（推荐，见任务 D）**：用书库文件夹 + 列表选择替代手输路径，从源头消除 `fs::read` 任意路径失败。**做了 D 就不用纠结 A 的路径问题了。**

**附带坑**：`ReadingPage.tsx` 输入框 placeholder 写「PDF / TXT」，但后端 `qq-st-bot/core/activity/pdf_reader.py` 只用 pypdf，**只支持 PDF，TXT 走不通**。做 D 时一并处理（要么后端加 TXT 分支，要么 UI 只标 PDF）。

---

## D. 一起看书专用文件夹（统一 data，免手输路径）

**后端现状（已摸清）**：
- 阅读会话存在 `data/runtime/activity/reading/{char_id}/{uid}/{session_id}/`，含 `metadata.json` + `pages/{n}.txt`（见 `core/data_paths.py:481-495`、`core/activity/activity_store.py`）。
- 每次开始阅读都是「上传 PDF → pypdf 逐页提取 → 存 session」，**没有"书库"概念**，源文件不留存。

**设计目标**：建一个统一的书库文件夹，UI 直接列书选读，不再手输路径；叶瑄的感悟也归档在一起。

**建议目录结构**（放在 `data/` 下走 sandbox，保持统一）：
```
data/library/
  books/                  ← 素材：用户放 PDF（后续可扩 TXT/EPUB）
  insights/{book_id}/     ← 叶瑄的感悟：每本书的读后笔记/批注
  covers/                 ← （可选）封面缩略
```

**后端改动**：
1. `core/data_paths.py` 加路径助手：`reading_library_root()` / `reading_library_books_dir()` / `reading_library_insights_dir(book_id=)`，并在 `core/data_registry.py` 注册（照 `reading_session_dir` 那条 PathMeta）。
2. 新增 `GET /activity/reading/library`（`admin/routers/reading.py`）：列出 `books/` 下的书（filename、大小、页数（可缓存）、上次读到第几页）。`book_id` 用文件名 hash（复用 `make_file_id`）。
3. `start_reading` 增加「从书库开始」路径：加可选字段 `library_filename`（或新端点 `POST /activity/reading/start_from_library`）。命中时后端直接从 `books/` 读字节，不走上传，其余逻辑（extract_pages → save session）复用。
4. 关闭阅读时，把现有 `generate_and_reflow` 产出的总结**同时写一份到 `insights/{book_id}/`**，作为"叶瑄的感悟"归档。

**前端改动**（`src/windows/activity/components/ReadingPage.tsx`）：
1. 把手输路径输入框换成**书库列表**（调新 `GET /activity/reading/library`），点一本即开读。
2. 加「添加书籍」：用 Tauri 文件选择器（`@tauri-apps/plugin-dialog` 已在依赖里）选 PDF → 新 Rust 命令把文件**拷进 `books/`**（而不是读任意路径），刷新列表。
3. `shared/api/activity-api.ts` + `src-tauri/src/lib.rs` 加对应命令（`activity_reading_library` 列表、`activity_reading_add_book` 拷贝、`activity_reading_start_from_library`）。

**验收**：UI 显示书库列表 → 点书直接开读 → 不再手输路径 → 关闭后 `insights/` 下生成感悟文件。

---

## B. 棋盘 UI：统一右侧 + 自适应 + 收起按钮 + 叶瑄主动说话

**现状（已摸清）**：
- 聊天面板是共用组件 `src/windows/activity/components/ActivityCompanionPanel.tsx`（`minWidth: 280, minHeight: 360`），左右/下方位置由**父页面布局**决定。
- 五子棋 `GomokuPage.tsx`：外层行 `display:flex, gap:24`（**不换行**），右列 `width:300, flexShrink:0` → 聊天稳定在右侧。棋盘是**固定像素**（`CELL`/`PAD`/`BOARD_SIZE` 常量，`BOARD_PX` 见第 24 行）。
- 国际象棋 `ChessPage.tsx`：外层行第 463 行 `flexWrap:'wrap'`，侧列 `minWidth:160, maxWidth:220`（**比面板 minWidth 280 还窄**），`SQUARE=54` 固定像素 → 窗口一窄，面板被挤换行到棋盘**下方**，且固定棋盘把聊天框挤出可视区/遮蔽。

**这就是「象棋聊天框在下方」和「缩小后聊天框被遮蔽」的根因**：固定像素棋盘 + 象棋侧列过窄 + flexWrap。

**改法**：

**B1 统一到右侧**：把 `ChessPage` 的布局对齐 `GomokuPage`——外层行去掉 `flexWrap:'wrap'`（或仅作最后兜底），右列宽度对齐五子棋（≥ 面板 minWidth），面板固定在右。

**B2 自适应缩小（棋盘+聊天一起缩）**：
- 棋盘改**响应式尺寸**：外层用 `flex:1, minWidth:0` 容纳棋盘区，用 `ResizeObserver`（或容器 100% + `aspect-ratio:1`）测量可用宽高，推导单元格大小：
  - 五子棋 `CELL = floor((size - 2*PAD) / (BOARD_SIZE-1))`
  - 象棋 `SQUARE = floor(size / 8)`
  取 `size = min(可用宽, 可用高)` 并设上下限（如 36–60px/格），让棋盘随窗口缩放。
- 聊天列改 `width: clamp(240px, 28%, 320px)`，`ActivityCompanionPanel` 的 `minWidth:280` 放宽成可收缩（`minWidth:0` + 内部内容自适应），避免硬挤。

**B3 收起按钮（仿 Claude 收起边栏）**：
- 在 `ActivityCompanionPanel` 顶栏（现有「和叶瑄说说」那行）右上角加一个收起按钮（chevron `»`）。
- 收起后整列塌成一条窄轨（~36px），显示展开按钮（`«`）。状态用 `uiPreferences`（如 `activity.companion.collapsed`）持久化，两个棋种共用。
- 收起时棋盘可用宽变大、自动放大（与 B2 的 ResizeObserver 联动）。

**B4 叶瑄下棋主动说话（频率我已设计如下）**：

> 目标：偶尔开口，不啰嗦。决策放后端，保证一致可测；前端只负责把返回的评论渲染进同一个聊天面板。

- **触发点**：每步走完后（用户落子已结算 + AI 应手返回时）评估一次。
- **必定开口（忽略冷却，关键事件）**：
  - 五子棋：形成活三/冲四、五连分胜负、开局第一手
  - 象棋：将军（`is_check`）、吃子（`captured_piece`）、升变、将死/和棋
- **随机开口**：基础概率 ~30%，但需满足**冷却 ≥3 步**（距上次开口），并设硬上限（约每 3–5 步最多一句），避免每步都说。
- **（可选）催促**：轮到用户后静置 ~45–60s，偶尔轻声提示一句（低优先，可后做）。
- **实现机制（推荐后端侧）**：
  - `admin/routers/gomoku.py`（`/move`、`/ai_move`）与 `admin/routers/chess.py`（`/move` 接 AI 后）在命中触发时，调用已有的 `gomoku_companion` / `chess_companion`（带 grounding facts）生成一句，作为响应里的可选字段 `companion_comment`（无则 `null`）返回。
  - 触发判定（概率/冷却/关键事件）写在引擎侧，用 session state 记 `last_comment_move_no`，只有命中才真正调 LLM（省开销）。
  - 前端 `ActivityCompanionPanel` 收到 `companion_comment` 就以「叶瑄」气泡追加进面板（复用现有消息渲染）。

**验收**：象棋聊天与五子棋一样在右侧；缩小窗口棋盘和聊天一起缩、聊天不被遮蔽；聊天右上角可收起/展开；对局中叶瑄偶尔主动评论（吃子/将军/活三等必评，平时约每 3–5 步一句）。

---

## C. 日记详情弹窗 → 可在全屏自由拖拽的独立窗口

**现状（已摸清）**：
- 日记详情用**应用内 panes 系统**打开：`SubDiary.tsx` 的 `openEntry()` → `panesApi.openPane(...)`（`windows/chat/components/Panes.tsx`）。
- pane 是 `position:absolute`，挂在一个 `position:fixed, inset:0` 的覆盖层里，拖拽被 `Math.min(window.innerWidth-200, …)` 钳制 → **永远出不了 tauri-app 主窗口**。
- 桌宠是**独立 OS 窗口**：`tauri.conf.json` 里 label `pet`，`main.tsx:11-31` 按 `?window=pet` 路由到 `<PetWindow/>`，`decorations:false / transparent / alwaysOnTop`；拖拽用 `getCurrentWindow().startDragging()`（`windows/pet/usePetMouse.ts:230`），所以能在整个屏幕自由拖。

**改法（仿桌宠做成独立窗口）**：
1. **运行时创建窗口**（日期是动态的）：在 `openEntry` 里改用 Tauri v2 `new WebviewWindow('diary-detail', { url: 'index.html?window=diary-detail&date=...&char=...', width:520, height:600, decorations:false, resizable:true })`（`import { WebviewWindow } from '@tauri-apps/api/webviewWindow'`）。已存在则 focus 复用。
2. **路由**：`main.tsx` 加分支 `windowView === 'diary-detail'` → 渲染新组件 `<DiaryDetailWindow/>`，从 URL 读 `date`/`char`，内部复用现有 `DiaryDetailPane`。
3. **拖拽**：该窗口顶栏 `onMouseDown` 调 `getCurrentWindow().startDragging()`（照搬 `usePetMouse.ts` 用法），无边框也能整屏拖。加一个关闭按钮（`getCurrentWindow().close()`）。
4. **权限（Tauri v2 必须）**：
   - `src-tauri/tauri.conf.json` 或运行时创建已够，但需在 `capabilities/` 加一份 `diary-detail.json`（`windows:["diary-detail"]`，含 `core:window:allow-start-dragging`、`allow-close`、`allow-set-position` 等，照 `capabilities/pet.json`）。
   - 主窗口 `capabilities/default.json` 需加创建窗口权限 `core:webview:allow-create-webview-window`（当前没有，会创建失败）。

**验收**：点日记条目弹出独立小窗 → 可拖出主窗口、在整个屏幕任意位置摆放 → 有关闭按钮 → 内容与原 pane 一致。

---

### 建议实现顺序
1. **D（+顺手解决 A）** — 看书文件夹，根治路径问题
2. **C** — 日记独立窗口，改动清晰
3. **B** — 棋盘 UI，改动最大（响应式棋盘 + 收起 + 主动说话三块可拆分提交）

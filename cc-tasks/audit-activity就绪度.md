# 审计 · activity「一起做事」就绪度（待办 e）

> 只读审计，不改码。核对 `qq-st-bot/core/activity/*` + `admin/routers/{activity,chess,gomoku,reading,dream_seed}.py` 与 `Emerald-client/src/windows/activity/*`。
> 核对日期 2026-06-14。

## 总览结论
**架构是完整的，不是"没架构"——"半成品"主要体现在外围（设置项占位、陪伴对话只接了五子棋），核心玩法四个都能端到端跑。**

- 单一权威声明点：`core/activity/registry.py` 的 `ACTIVITY_REGISTRY`（4 个活动，均 `enabled=True`）。
- 记忆策略显式声明：`MemoryPolicy` 默认**不写** short_term / hidden_state / event_log（`main_memory` 多为 `deferred`/`none`）——隔离干净，但也意味着"一起做事"基本**不进主记忆**（见缺口 D）。
- 有 contract smoke test（route / Tauri command / 前端 key / memory policy 断言）。
- 4 个活动都在 `ActivityHomePage` 以卡片列出、可进入。

## 四活动就绪度

| 活动 | 后端端点 | 前端页 | 玩法可用 | 陪伴对话 | 备注 |
|---|---|---|---|---|---|
| **gomoku 五子棋** | start/state/move/close/**ai_move**/**chat** (6) | GomokuPage 437行 | ✅ | ✅ 有 `/chat` + **grounding facts**（连几子/挡截/靠中心） | **最完整**，是其他活动的参照标杆 |
| **chess 国际象棋** | start/state/move/legal_moves/close (5) | ChessPage 431行 | ✅ 含合法走法高亮 | ❌ **无 chat 端点** | 能下棋，但下棋时不能跟叶瑄聊天/没有解说 |
| **reading 一起看书** | start/state/page/turn_page/close (5) | ReadingPage 217行 | ✅ PDF/TXT 逐页 | ❌ 无 chat 端点 | 能读，但没有"边读边聊"的陪伴 |
| **dream_seed 梦境预构** | start/state/**chat**/close (4) | DreamSeedPanel 172行 | ✅ | ✅ 有自己的 `/chat` | 独立面板，不走共享 CompanionPanel |

## 具体"半成品"缺口

### A. 活动设置全是占位（未接线）⚠ 最显眼
`ActivitySettingsPage.tsx` 有个 `PlaceholderSelect`（`<select disabled>`），用在这些设置上、**全部没接后端/没生效**：
- 阅读「字体大小」「页面宽度」
- 棋类「棋盘颜色」「棋子样式」
- 「显示调试信息（session_id / FEN）」
（注：同页的「日间/夜间主题」「安全/危险模式」已经是真功能，不是占位。）
→ 这是"半成品感"的主要来源：设置面板看着有、其实大半是死控件。

### B. 陪伴对话覆盖不统一 ⚠
- 共享的 `ActivityCompanionPanel.tsx` **只 import `gomokuApi` + GomokuGroundingFacts**，即"边做事边和叶瑄聊"目前**只有五子棋**有（还带依据提示）。
- chess、reading **后端没有 chat 端点**，自然没有陪伴对话。
- dream_seed 有自己的 `/chat` 但走独立面板，不统一。
→ 想要的"一起做事时叶瑄在旁边搭话"在 4 个活动间不一致。

### C. grounding（依据）只有五子棋
gomoku 有 `gomoku_grounding`（落子形成几连/挡截/靠中心等客观依据喂给叶瑄），chess/reading 无对应"叶瑄知道盘面/读到哪"的 grounding。

### D. 活动基本不进主记忆（按设计，但你可能想要）
`MemoryPolicy` 默认不写 short_term/hidden_state/event_log，`main_memory` 多为 deferred/none。所以"我们一起下过棋/读过书"**不会沉淀进叶瑄的长期记忆**。这是当前设计的有意隔离，但如果你想要"叶瑄记得我们做过的事"，需要单独决定哪些活动结束摘要回流主记忆（registry 已留 `summary_threshold`/`main_memory:"deferred"` 接口）。

## 建议（若要收口 e，按性价比）
1. **统一陪伴对话**（B/C）：给 chess、reading 补 `/chat` 端点 + grounding（chess 盘面 FEN/最近一步、reading 当前页摘要），让 `CompanionPanel` 按 `activityId` 适配各活动——这是"半成品感"最大、收益最高的一项。
2. **接活动设置**（A）：把 `PlaceholderSelect` 换成真控件（阅读字号/宽度走前端 uiPref 即可，棋盘配色同理；调试开关接 state 显示）。轻量、纯前端。
3. **活动记忆回流**（D）：决定哪些活动结束写一条摘要进主记忆（设计决策，需配合 `docs/memory.md` 的固化链）。
4. dream_seed 是否并入共享 CompanionPanel 视觉统一（可选）。

## 这份审计之后
若你要做，建议拆成施工文档（待你点）：
- `12a-活动陪伴对话统一.md`（B/C，跨双仓，中等）
- `12b-活动设置接线.md`（A，纯前端，小）
- `12c-活动记忆回流.md`（D，后端 + 设计决策，中）

> 当前我未擅自动手——e 本来就是"先搞清楚做到哪"。要做哪几项告诉我即可。

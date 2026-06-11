# docs/garden.md — 花园系统

---

## 定位

花园是一个独立于对话 prompt 的情绪伴生系统：调度器按当前 `mood_state` 给对应花槽自动浇水，用户催浇花时可走工具，被动/主动事件再通过调度器让他自然提一句。

当前花园状态**不会直接注入 prompt**；只有浇水工具结果、开花、采后处理、花瓶枯萎等事件会变成一次普通调度器消息。

---

## 代码入口

| 功能 | 文件 |
|---|---|
| 花园核心逻辑 | `core/garden/manager.py` |
| 花种、阶段、概率常量 | `core/garden/constants.py` |
| 数据路径 | `core/sandbox.py` → `DataPaths.garden()` |
| 被动浇水工具 | `core/tools/garden_tools.py` |
| 工具注册 | `core/tool_dispatcher.py` → `water_garden` |
| 自动浇水触发器 | `core/scheduler/triggers/garden_water.py` |
| 每日采后扫描触发器 | `core/scheduler/triggers/garden_daily.py` |
| 调度器注册 | `core/scheduler/loop.py` |
| 管理面板状态接口 | `admin/routers/garden.py` |
| 路由挂载 | `admin/admin_server.py` |

---

## 数据文件

路径统一走 `get_paths().garden()`，生产环境位于
`data/runtime/characters/{char_id}/garden/`，测试模式会整体偏移到
`data/test_sandbox/{session}/runtime/characters/{char_id}/garden/`。

| 文件 | 内容 |
|---|---|
| `plants.json` | 五个花槽当前状态：花种、阶段、growth、播种/浇水/开花时间 |
| `storage.json` | `harvest` / `vase` / `history`，保存开花后的收获、花瓶和历史记录 |

初次读取或浇水时，`_bootstrap()` 会自动创建五个槽位和空仓库。

---

## 生长机制

五个槽位按情绪映射：

| 槽位 | 花 | mood |
|---|---|---|
| `calm` | 雏菊 | `neutral` / `gentle` |
| `bright` | 向日葵 | `happy` / `surprised` |
| `low` | 蓝铃 | `sad` |
| `yandere` | 红玫瑰 | `yandere` / `angry` |
| `adrift` | 蒲公英 | `thinking` / `sleepy` |

每次浇水 `growth += 10`。阶段阈值：

| stage | growth |
|---|---|
| `seed` | 0 |
| `sprout` | 100 |
| `budding` | 200 |
| `bloom` | 300 |

到达 `bloom` 时，当前花进入 `storage.harvest`，槽位立即重新播种；返回结果里会带 `events: [{"type": "bloom", ...}]`。

---

## 浇水路径

### 自动浇水

`garden_water` 冷却 300 分钟；触发后有 30% 概率命中。

```
_check_garden_water()
  → _is_ready("garden_water")
  → _mark("garden_water")
  → garden_manager.auto_water_tick()
      → mood_state.get_current()
      → mood 映射到 slot_key
      → water(slot_key, reason="auto")
```

自动浇水本身不发言；开花事件先进入短期事件缓存。当前 `EXECUTE_MODE="live"` 时由
`propose_garden_bloom()` 报名，gating 选中后经统一 `execute_prompt()` 调用
`_pipeline_send(..., trigger_name="garden_bloom")`。

### 被动浇水工具

`water_garden` 注册为 `info` 类工具，因此会被 pre-pipeline 探针覆盖：

- 触发例句：`你今天去浇花了吗`、`快去浇花`、`花园里的花怎么样了`
- 关键词：`浇花`、`花园`、`浇水`
- 实现：`core/tools/garden_tools.py` → `garden_manager.force_water()`

工具按当前心情选择槽位，返回一段状态描述给 LLM，最终由他自然回复。

---

## 每日采后扫描

`garden_daily` 冷却 24 小时，负责处理 `storage.harvest` 和 `storage.vase`：

| 事件 | 条件 | 状态变化 | 发言策略 |
|---|---|---|---|
| `harvest_expired` | `now > expires_at` | 从 `harvest` 移到 `history`，标记 `expired` | 30% sample |
| `harvest_handle` / `ask` | 开花超过 3 天且未处理 | 标记 `handle_triggered` | 必走 `_pipeline_send`，但仍受用户活跃窗口影响 |
| `harvest_handle` / `dry` | 随机处理分支 | 标记 `dried` | 30% sample |
| `harvest_handle` / `vase` | 随机处理分支 | 进入 `vase`，从 `harvest` 移除 | 30% sample |
| `harvest_handle` / `gift` | 随机处理分支 | 写 `gifted_note` | 必走 `_pipeline_send`，但仍受用户活跃窗口影响 |
| `harvest_handle` / `silent` | 随机处理分支 | 只标记已处理 | 不发言 |
| `vase_wilted` | `now > wilts_at` | 从 `vase` 移到 `history`，标记 `wilted` | 30% sample |

处理概率：

- `ask`: 0.00-0.30
- `dry/vase`: 0.30-0.60
- `gift`: 0.60-0.80
- `silent`: 0.80-1.00

---

## 管理面板接口

`GET /garden/state`

需要管理面板 token，返回：

- `slots`：五个花槽的展示数据，含 `stage_progress`
- `harvest_count`：收获区数量
- `vase_count`：花瓶数量

接口只读取和必要时初始化状态，不执行浇水。

---

## 当前边界

1. 写入目前使用普通 `Path.write_text()`，没有接入 `safe_write` 或锁；现在已有 `garden_water`、`garden_daily`、`water_garden` 三条写路径，后续最好补 garden 专用锁。
2. `garden_bloom`、`garden_handle_*`、`garden_vase_wilted` 已有原生 proposer 和独立冷却；
   事件进入缓存后由 gating 每 tick 最多选择一个，只有真实发送成功才 mark。`garden_water` /
   `garden_daily` 扫描本体仍按原冷却执行状态变化。
3. `ask` / `gift` / `dry` 分支会标记 `handle_triggered`，其中只有 `vase` 会从 `harvest` 移除；如果设计上“送给用户/做成干花”也应离开 harvest，需要补状态迁移。

# Spec #7 — 玩耍模式（Toy Play Mode）

> 状态：已实现
> 难度：中
> 改动范围：后端 `core/pipeline.py`（intent 推送）；前端 Emerald-client
> 新增 `src/windows/toy/`、`src/shared/playMode.ts`、`src/shared/api/hardware.ts`，
> 修改 `main.tsx`、`ChatWindow.tsx`、`Ribbon.tsx`、`shared/api/ws.ts`、`shared/api/types.ts`、
> `src-tauri/src/lib.rs`。

---

## 目标行为

用户在偏好「其他」页开启「玩耍模式」后：

1. 现实对话里 `{char}` 表达「想和你玩玩具 / 一起玩 / 打开玩耍模式」等当下、第一人称、主动邀请语义时，
   Path B 意图解析检测到 `toy_invite`，后端经 `_push_desktop_action` 推送 `{type: toy_invite}`。
2. 前端收到 `toy_invite`：仅当玩耍模式开关开启时打开 ToyWindow（关闭时忽略，仍正常 ack）。
3. 也可在 Chat Ribbon 的玩耍模式按钮手动打开（按钮仅在开关开启时显示）。

ToyWindow 与 ActivityWindow（一起做事）同级：由 `main.tsx` 的 `activeWindow` 状态切换挂载，
作为覆盖层显示，ChatWindow / ChatPanel 保持挂载，WS 订阅不中断。布局为左侧 Ribbon +
左侧栏（toy 状态 + 系统/蓝牙状态）+ 右聊天页。

## 硬件链路（复用 Spec #6）

```
toy  ⇄(蓝牙)⇄  Intiface Central(本机, ws://127.0.0.1:12345)  ⇄(本地WS)⇄  qq-st-bot 后端
```

设备控制工具 `toy_vibrate / toy_stop / toy_pattern` 已在 Spec #6 实现，owner 私聊门控，
经 info/desktop 探针触发。玩耍模式窗口只是监控 + 聊天表现层，不改变设备控制门控。

状态来源：`GET /hardware/devices` → `{connected, devices:[{index,name,display_name,can_vibrate}]}`；
`POST /hardware/connect` → `{success}`。其中 `connected` 即 Intiface 连接状态（系统/蓝牙状态显示），
`devices` 即 toy 状态显示。

## 后端实现

`core/pipeline.py` `_parse_and_execute_intent()` 的 `intent_prompt` 在 `dream_invite` 之后追加
`toy_invite` 动作说明。`toy_invite` 非危险动作，自然继承 Path B 三道守卫
（trigger_name 为空、user_content 非空、非危险动作）与 120s 幂等窗口，`_push_desktop_action`
原样推出，无需改动调度层。

后端 emit 不做开关门控（与 dream_invite 一致），由前端「玩耍模式」开关做 opt-in 门控。

## 前端实现

- `shared/playMode.ts`：`isPlayModeEnabled / setPlayModeEnabled`（localStorage UI 偏好 `playMode.enabled`，默认 false）。
- `shared/api/hardware.ts`：`getHardwareDevices() / connectHardware()`，经 Tauri `hardware_get_devices / hardware_connect` 代理后端。
- `src-tauri/src/lib.rs`：新增上述两个命令，mirror `dream_get_state` 的 `authorized_request + backend_url` 模式。
- `shared/api/types.ts`：`DesktopActionType` 增 `toy_invite`。
- `shared/api/ws.ts`：`WSEvents` 增 `toy_invite`；`_dispatchAction` 增 `case 'toy_invite'` → `emit('toy_invite', {})`。
- `windows/toy/`：`ToyWindow`（状态机：home/chat），`ToyRibbon`，`ToySidebar`（toy + 系统状态，轮询 hardware），`ToyChatPanel`（复用 `sendChat`，append-only）。
- `main.tsx`：`activeWindow` 增 `'toy'`，渲染 `ToyWindow`，传 `onToyOpen` 给 ChatWindow。
- `ChatWindow.tsx`：接 `onToyOpen`；订阅 `wsClient.on('toy_invite')`，开关开启才调 `onToyOpen`；偏好「其他」页加开关；传 `playModeEnabled + onToyOpen` 给 Ribbon。
- `Ribbon.tsx`：开关开启时显示玩耍模式入口按钮。

## 验证方式

1. `pytest tests/test_intent_grounding.py -k toy_invite`：角色邀请玩耍时 Path B 推送 `{type: toy_invite}`。
2. 启动 bot + 桌宠，偏好开启玩耍模式，对话里说「我们一起玩会儿吧」，观察后端日志 `[pipeline.intent] action=toy_invite`，前端 ToyWindow 自动弹出。
3. 关闭开关后重复，ToyWindow 不应弹出。
4. 本机跑 Intiface Central 并配对设备，ToySidebar 显示 connected + 设备名。

## 注意事项

- 玩耍模式开关仅前端 opt-in；后端探针照常运行（与 dream_invite 一致）。若需后端也门控，可在 emit 前加 config 检查。
- `toy_invite` 不要加入 `_INTENT_DANGEROUS_ACTIONS`。
- ToyWindow 自包含，不读写 Chat messages/state/session；聊天经 `sendChat` 走 `/desktop/chat`，回复同样经 WS 同步到主聊天。

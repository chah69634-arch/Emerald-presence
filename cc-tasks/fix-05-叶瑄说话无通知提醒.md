# FIX-05 · 叶瑄说话时任务栏图标不亮、无弹窗提醒

> **前端（Emerald-client，Tauri v2）**。仓库根 `D:\ai\Emerald-client`。
> 先读 `Emerald-client/ARCHITECTURE.md` + `src-tauri/src/lib.rs`（command 注册）+ `src/shared/api/ws.ts`。

## 现象

叶瑄发消息时，如果 Chat 窗口没在前台/最小化了，**底部任务栏的应用图标不会高亮闪烁**，也**没有任何弹窗/系统通知**，用户完全感知不到来消息了。

## 现状（已核对，根因）

1. **没有任务栏 attention/闪烁**：全仓 `src-tauri` 只有 `actions.rs:109` 一处 `set_focus`，**没有任何 `request_user_attention` / `UserAttentionType` 调用**。Tauri 的 `WebviewWindow::request_user_attention(Some(UserAttentionType::Informational))` 正是用来让 Windows 任务栏图标闪烁/高亮的，当前根本没用。
2. **没有系统通知**：`package.json` / `Cargo.toml` **未引入 `tauri-plugin-notification`**。唯一的"通知"是 `actions.rs:27 action_show_notify`，但它走的是 `app.dialog().message(...)` —— 一个**模态对话框**（抢焦点、要点确定），不是任务栏通知，UX 不对。
3. **正常说话根本不触发提醒**：`action_show_notify` 只在收到显式 `show_notify` 桌面动作时才调用（`ws.ts:275`）。叶瑄正常聊天消息走的是 `channel_message` / `message_stream_*` 事件（`ws.ts:179-203`），消费点在 `src/windows/chat/components/ChatPanel.tsx:1147` 和 `GroupChatPanel.tsx:488`，**这条链上没有任何提醒钩子**。

→ 三者叠加：正常消息既不闪任务栏也不弹通知。

## 设计 / 实现

目标：消息到达且 Chat 窗口**未聚焦或不可见**时，(1) 任务栏图标闪烁，(2) 弹一条系统通知（非模态 dialog）。

1. **任务栏闪烁（必做，成本最低）**
   - 新增 Tauri command（如 `action_request_attention`）：
     ```rust
     window.request_user_attention(Some(tauri::UserAttentionType::Informational))
         .map_err(|e| e.to_string())
     ```
     在 `lib.rs` 的 `invoke_handler` 注册（参照 `actions::action_show_notify` 的注册位 `lib.rs:1456`）。
   - 窗口重新聚焦时 attention 一般自动清除；如需手动清，可在 focus 事件里 `request_user_attention(None)`。

2. **系统通知（弹窗提醒）**
   - 引入 `tauri-plugin-notification`（v2）：加 `Cargo.toml` 依赖 + `lib.rs` 注册插件 + `package.json` 加 `@tauri-apps/plugin-notification` + 在 capabilities 里放行 `notification:default` 权限。
   - 收到消息且窗口未聚焦时推送通知（标题=角色名，正文=消息摘要，截断）。
   - **不要再用 `action_show_notify` 的模态 dialog** 做常规消息提醒（保留它给真正需要确认的场景即可）。

3. **触发钩子（关键接线）**
   - 在 `channel_message` / `message_stream_end` 的消费侧（`ChatPanel.tsx:1147`、`GroupChatPanel.tsx:488`）判断窗口可见性：用 `getCurrentWindow().isFocused()` / `isVisible()`（`@tauri-apps/api/window`）。
   - 未聚焦 → 调闪烁 command +（可选）系统通知；聚焦 → 不打扰。
   - 流式消息只在 `message_stream_end` 触发一次，避免每个 delta 都闪。
   - 做节流/去重（同一 `msg_id`/`round_id` 只提醒一次）。

## 验收

- Chat 窗口最小化/失焦时，叶瑄发消息 → Windows 任务栏图标闪烁高亮。
- 同场景下弹出一条系统通知（非模态对话框），点了不抢断当前操作。
- 窗口在前台时不弹通知、不闪烁（不打扰）。
- 流式回复只提醒一次，不随 delta 抖动。
- 群聊路径（GroupChatPanel）同样生效。

## 备注

闪烁（步骤 1）是最小可见改动，可先单独落地验证体感；系统通知（步骤 2）涉及加插件+权限，稍重。两步可分先后。

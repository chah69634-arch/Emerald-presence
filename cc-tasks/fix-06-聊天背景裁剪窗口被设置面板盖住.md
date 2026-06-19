# FIX-06 · 更换聊天背景时裁剪窗口被设置面板盖住，点一下直接退出

> **前端（Emerald-client，React + Tauri）**。仓库根 `D:\ai\Emerald-client`。
> 相关文件：`src/windows/chat/ChatWindow.tsx`、`src/windows/dream/components/DreamBackgroundCropper.tsx`、`src/features/dream/DreamTokens.css`。

## 现象

在「偏好 / 外观 / 聊天背景」选图后，裁剪窗口出现在设置面板**下方**（被设置遮罩盖住），点击裁剪区时直接把设置面板关掉了，**走不完裁剪流程**。

## 现状（已核对，根因）

层级冲突，纯前端 z-index/定位问题：

- 设置面板（偏好）是一个 `position: fixed; zIndex: 110` 的全屏遮罩，**背景层 `onClick={onClose}`**（`ChatWindow.tsx:132-135`），内层面板 `stopPropagation`。
- 聊天背景的裁剪器用的是 `DreamBackgroundCropper`（`ChatWindow.tsx:123-124`），其样式来自 CSS 类 `.dream-background-cropper`（`DreamTokens.css:1855-1858`）：
  ```css
  position: absolute;   /* 不是 fixed */
  inset: 0;
  z-index: 40;          /* 远低于设置面板的 110 */
  ```
- → 裁剪器 z-index 40 < 设置遮罩 110，被盖在底下；用户点"裁剪窗口"，实际点到的是上层设置遮罩的背景 → 触发 `onClose` → 整个设置+裁剪流程被关掉。

对照：头像裁剪器 `AvatarCropper` 用内联 `position: fixed; zIndex: 120`（`AvatarCropper.tsx:38`），**高于 110**，所以头像裁剪一切正常。问题只出在聊天背景这条用了 `DreamBackgroundCropper` 的路径。

⚠ 注意：`DreamBackgroundCropper` **被两处复用**——聊天背景（`ChatWindow.tsx:124`）和梦境窗偏好（`DreamPrefsPane.tsx:570`）。梦境窗里它在自己的容器内、`absolute/z-40` 是合适的。**直接改共享 CSS 会误伤梦境窗**。

## 实现（推荐：只在聊天上下文抬高层级，不动共享 CSS）

- 方案 A（推荐）：在 `ChatWindow.tsx` 渲染 `DreamBackgroundCropper` 时，用一个 `position: fixed; zIndex: 120` 的包裹层把它套在设置遮罩之上；或给它传一个 chat 专用的覆盖 class，在聊天场景把 `position` 提为 `fixed`、`z-index` 提到 `≥ 120`（与 AvatarCropper 对齐）。保持 `DreamTokens.css` 原值不变，梦境窗不受影响。
- 方案 B：让 `DreamBackgroundCropper` 接受一个可选 `zIndex`/`variant` prop，聊天场景传高层级值，默认仍是梦境窗的 40/absolute。
- 同时确认：裁剪器一旦在设置遮罩之上，其自身的点击不会冒泡到设置遮罩的 `onClose`（裁剪器是独立 fixed 层即可，天然不在设置 DOM 内；若仍有冒泡风险，给裁剪器根节点加 `stopPropagation`）。

> 不建议把设置遮罩的 `onClick=onClose` 去掉——点背景关闭是预期交互，问题在裁剪器没浮到它上面。

## 验收

- 「偏好 → 聊天背景」选图后，裁剪窗口浮在设置面板**之上**，可正常缩放/拖动/确认导入，走完整个流程。
- 裁剪过程中点击裁剪区不会误关设置面板。
- 头像裁剪（AvatarCropper）行为不变。
- 梦境窗（DreamPrefsPane）里的背景裁剪行为不变（共享 CSS 未被破坏）。

## 备注

小改动、纯前端。改完用 `npm run build` 验证（沙箱里 Vite 可能因 `node_modules/.vite-temp` 权限报 EPERM，参照 qq-st-bot `docs/dev-environment.md` 第 3 条申请权限后原命令重跑）。

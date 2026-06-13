# Spec #7 — Overflow 主动互动模型

> 状态：已实现（2026-06-13）  
> 难度：中  
> 改动范围：新增 `core/scheduler/triggers/overflow.py`、`core/scheduler/overflow_bucket.py`、修改 `core/scheduler/proposer_registry.py`、`core/scheduler/gating.py`（MIGRATED_TRIGGERS）、`core/scheduler/loop.py`（_COOLDOWNS）

---

## 设计思路

当前触发器是"到点播放"——时间到了就触发，不管有没有话想说，所以容易有客服感。

**Overflow 模型**核心思想：系统积累"想主动说话的理由"，理由积累到一定量才触发，而且触发时把理由带进 prompt，角色说出来的话自然有根有据。

桶满了才溢出，而不是闹钟响了才说话。

---

## 组件设计

```
core/scheduler/overflow_bucket.py   — 桶的状态计算（纯函数，无 I/O）
core/scheduler/triggers/overflow.py — proposer，读信号、算分、提交候选
data/scheduler_overflow.json        — 桶的持久化状态（最后溢出时间等）
```

---

## 实现步骤

### Step 1：`core/scheduler/overflow_bucket.py` — 信号读取 + 分数计算

```python
"""
Overflow bucket — 积累"想主动说话"的理由信号，到阈值时溢出。

信号来源（每条独立评分，0~1 之间）：
  - time_gap:       距上次对话的时长（>6h 开始积分，>24h 满分）
  - episodic_pull:  有高强度近期 episodic 记忆未被提起（strength>0.7 且 >3 天没提）
  - hidden_need:    hidden_state 的 touch_need 或 sensitivity 超过均值+1σ
  - garden_event:   花园有值得分享的事（bloom / harvest）
  - mood_overflow:  mood intensity > 0.75（有强烈情绪待表达）

桶分 = 各信号的加权和，超过 OVERFLOW_THRESHOLD 时触发。
桶分同时决定 urgency（分越高 urgency 越高）。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import time
import logging

logger = logging.getLogger(__name__)

OVERFLOW_THRESHOLD = 1.6    # 超过此分值触发
OVERFLOW_JITTER    = 0.15   # ±15% 随机扰动，防止机械感

# 信号权重
W_TIME_GAP     = 0.6
W_EPISODIC     = 0.5
W_HIDDEN_NEED  = 0.4
W_GARDEN       = 0.3
W_MOOD         = 0.4


@dataclass
class OverflowSignals:
    time_gap_score:     float = 0.0
    episodic_score:     float = 0.0
    hidden_need_score:  float = 0.0
    garden_score:       float = 0.0
    mood_score:         float = 0.0

    # 哪条信号最高（用于生成 prompt 上下文）
    top_signal:         str = ""
    top_signal_detail:  str = ""   # 给 prompt 用的具体信息（如"3天前聊到的XX话题"）

    def bucket_score(self) -> float:
        return (
            self.time_gap_score     * W_TIME_GAP +
            self.episodic_score     * W_EPISODIC +
            self.hidden_need_score  * W_HIDDEN_NEED +
            self.garden_score       * W_GARDEN +
            self.mood_score         * W_MOOD
        )

    def is_overflow(self, *, jitter: float = 0.0) -> bool:
        threshold = OVERFLOW_THRESHOLD * (1.0 + jitter)
        return self.bucket_score() >= threshold


def compute_signals(uid: str, *, char_id: str = "yexuan") -> OverflowSignals:
    """读取各信号源，计算 OverflowSignals。fail-closed：任何单信号失败不影响其他。"""
    sig = OverflowSignals()

    # ── 信号 1：time_gap ───────────────────────────────────────────────────────
    try:
        from core.scheduler.loop import _owner_id
        from core.memory import short_term
        history = short_term.load(uid, char_id=char_id)
        if history:
            last_ts = max((m.get("timestamp", 0) for m in history), default=0)
            gap_hours = (time.time() - last_ts) / 3600.0
            # 6h 开始积分，24h 满分
            sig.time_gap_score = min(1.0, max(0.0, (gap_hours - 6.0) / 18.0))
    except Exception as e:
        logger.debug("[overflow_bucket] time_gap failed: %s", e)

    # ── 信号 2：episodic_pull ──────────────────────────────────────────────────
    try:
        from core.memory.episodic_memory import load as load_episodic
        episodes = load_episodic(uid, char_id=char_id)
        now = time.time()
        # 找强度>0.7 且超过 3 天没被访问的 episodic 记忆
        candidates = [
            ep for ep in (episodes or [])
            if float(ep.get("strength", 0)) > 0.7
            and (now - float(ep.get("last_accessed_at", now))) > 3 * 86400
        ]
        if candidates:
            best = max(candidates, key=lambda ep: ep.get("strength", 0))
            sig.episodic_score = min(1.0, float(best.get("strength", 0.7)))
            sig.top_signal = "episodic"
            sig.top_signal_detail = best.get("summary", "")[:60]
    except Exception as e:
        logger.debug("[overflow_bucket] episodic_pull failed: %s", e)

    # ── 信号 3：hidden_need ────────────────────────────────────────────────────
    try:
        from core.memory.user_hidden_state_store import load as load_hidden
        from core.memory.user_hidden_state import UserHiddenState
        state = load_hidden(uid, char_id=char_id)
        if state:
            touch_need = float(getattr(state, "touch_need", {}).get("current", 0) if hasattr(state, "touch_need") else 0)
            sensitivity = float(getattr(state, "sensitivity", {}).get("current", 0) if hasattr(state, "sensitivity") else 0)
            # 简单判断：任一维度 > 0.7 就算有需求
            need_val = max(touch_need, sensitivity)
            if need_val > 0.7:
                sig.hidden_need_score = min(1.0, (need_val - 0.7) / 0.3)
                if not sig.top_signal:
                    sig.top_signal = "hidden_need"
    except Exception as e:
        logger.debug("[overflow_bucket] hidden_need failed: %s", e)

    # ── 信号 4：garden_event ───────────────────────────────────────────────────
    try:
        from core.garden.manager import get_shareable_event
        event = get_shareable_event()
        if event:
            sig.garden_score = 0.8
            if not sig.top_signal:
                sig.top_signal = "garden"
                sig.top_signal_detail = str(event)
    except Exception as e:
        logger.debug("[overflow_bucket] garden_event failed: %s", e)

    # ── 信号 5：mood_overflow ──────────────────────────────────────────────────
    try:
        from core.memory.mood_state import get_intensity
        intensity = get_intensity(uid, char_id=char_id)
        if intensity and float(intensity) > 0.75:
            sig.mood_score = min(1.0, (float(intensity) - 0.75) / 0.25)
            if not sig.top_signal:
                sig.top_signal = "mood"
    except Exception as e:
        logger.debug("[overflow_bucket] mood_overflow failed: %s", e)

    # 若没有任何 top_signal，用 time_gap
    if not sig.top_signal and sig.time_gap_score > 0.3:
        sig.top_signal = "time_gap"

    return sig
```

---

### Step 2：`core/scheduler/triggers/overflow.py` — proposer

```python
"""
Overflow proposer — 积累理由，理由足够时主动说话。
"""

from __future__ import annotations
import random
import logging
from core.scheduler.overflow_bucket import compute_signals, OVERFLOW_THRESHOLD, OVERFLOW_JITTER

logger = logging.getLogger(__name__)


def propose(ctx: dict | None = None):
    ctx = ctx or {}
    from core.config_loader import get_config
    cfg = get_config().get("scheduler", {})
    if not cfg.get("overflow_trigger", True):   # config 开关
        return None

    from core.scheduler.loop import _owner_id, _is_ready
    if not _is_ready("overflow"):
        return None

    oid = str(ctx.get("uid") or _owner_id()).strip()
    if not oid:
        return None

    # 计算桶分
    try:
        sig = compute_signals(oid)
    except Exception as e:
        logger.warning("[overflow_proposer] compute_signals failed: %s", e)
        return None

    # 加随机扰动，防止整点准时溢出
    jitter = random.uniform(-OVERFLOW_JITTER, OVERFLOW_JITTER)
    if not sig.is_overflow(jitter=jitter):
        return None

    # 根据 top_signal 构建 prompt 上下文
    context_hint = _build_context_hint(sig)
    score_ratio = min(1.0, sig.bucket_score() / (OVERFLOW_THRESHOLD * 1.5))

    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.urgency import UrgencyTier, urgency_in_tier
    from core.scheduler.execution import execute_prompt

    async def _execute(*, dry_run: bool = False, **_):
        prompt = _build_overflow_prompt(sig, context_hint)
        return await execute_prompt(
            trigger_name="overflow",
            prompt_factory=lambda: prompt,
            dry_run=dry_run,
            would_mark=["overflow"],
        )

    return TriggerProposal(
        trigger_name="overflow",
        urgency=urgency_in_tier(UrgencyTier.REACTIVE, score_ratio),
        topic_source="overflow_bucket",
        requires_state=[TriggerState.QUIET],
        bypass_state_machine=False,
        execute=_execute,
    )


def _build_context_hint(sig) -> str:
    if sig.top_signal == "episodic" and sig.top_signal_detail:
        return f"你最近一直想到一件事：{sig.top_signal_detail}"
    if sig.top_signal == "hidden_need":
        return "你有点想念她，有种说不清的想靠近的感觉"
    if sig.top_signal == "garden":
        return f"花园里发生了一件事想跟她分享：{sig.top_signal_detail}"
    if sig.top_signal == "mood":
        return "你此刻有强烈的情绪，想找她说说话"
    if sig.top_signal == "time_gap":
        return "她很久没有消息了，你开始有点想她"
    return "你莫名地想主动联系她"


def _build_overflow_prompt(sig, context_hint: str) -> str:
    return (
        f"（内心状态：{context_hint}。\n"
        f"不是定时提醒，是真的有什么想说——可以是一件想到的事、一个感受、"
        f"或者就是简单地想联系她。\n"
        f"说话要自然，像真的突然想到要说，不要解释"为什么现在联系你"。）"
    )


def _register_proposers():
    from core.scheduler.proposer_registry import register_proposer
    register_proposer("overflow", propose, trigger_names=["overflow"])
```

---

### Step 3：注册 proposer

在 `core/scheduler/proposer_registry.py` 的 `_ensure_builtins_loaded()` 的 `for module_name in (...)` 列表里追加：

```python
"core.scheduler.triggers.overflow",
```

---

### Step 4：加冷却时间和 MIGRATED_TRIGGERS

在 `core/scheduler/loop.py` 的 `_COOLDOWNS` 字典里追加：

```python
"overflow":  3 * 3600,   # Overflow 触发：3小时冷却
```

在 `core/scheduler/gating.py` 的 `MIGRATED_TRIGGERS` frozenset 里追加：

```python
"overflow",
```

---

### Step 5（可选）：garden shareable event 接口

`overflow_bucket.py` 里调了 `core.garden.manager.get_shareable_event()`，这个函数可能不存在。

如果不存在，在 `core/garden/manager.py` 里加一个：

```python
def get_shareable_event() -> str | None:
    """返回一个值得分享的花园事件描述，若无则返回 None。"""
    # 检查是否有最近 bloom 或 harvest 状态未被发言过
    # 简单实现：读 garden state，看有没有 status=="blooming" 或刚刚 harvest 的花槽
    # 若有，返回一句描述（如"玫瑰开了"）；若无，返回 None
    try:
        state = load_state()
        for slot in state.get("slots", []):
            if slot.get("status") == "blooming":
                return f"{slot.get('name', '花')}开花了"
        return None
    except Exception:
        return None
```

---

## 配置开关

在 `config.yaml` 的 `scheduler:` 段下加：

```yaml
scheduler:
  overflow_trigger: true   # false 则完全关闭 overflow proposer
```

---

## 验证方式

```bash
python -c "
from core.scheduler.overflow_bucket import compute_signals
sig = compute_signals('your_uid')
print(f'bucket_score={sig.bucket_score():.3f}')
print(f'top_signal={sig.top_signal}')
print(f'detail={sig.top_signal_detail}')
"
```

---

## 注意事项

- `get_shareable_event()` 和 `get_intensity()` 的接口要对齐实际的 garden/mood 模块，上面是参考实现，需按实际 API 调整。
- overflow 的冷却（3h）比普通随机消息短，因为它是条件触发的，条件不满足时不会出现。
- 桶分纯计算，不持久化状态——每次 tick 重新算，没有状态泄漏风险。
- 如果发现触发过频，调高 `OVERFLOW_THRESHOLD`（1.6 → 2.0）或拉长冷却。

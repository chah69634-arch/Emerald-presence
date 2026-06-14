# CC-08b · hidden_state 现实写入链接线方案

> 本文件是 CC-08 交付的 follow-up 计划。**不要在这里直接施工**——先确定信号映射、评审后再接。

---

## 背景

Phase 3 已实现三条 integrator 函数，但从未接进回合管线：

| 函数 | 文件 | 零调用原因 |
|---|---|---|
| `integrate_event_and_save` | `user_hidden_state_integrator.py` | 信号→RealityEventType 映射未定 |
| `integrate_impression_and_save` | 同上 | ImpressionInput 字段映射未定 |
| `integrate_body_cue_and_save` | 同上 | 触发时机未定（暂不接） |

运行时唯一写入来源：出梦 afterglow、12h 衰减、7d 基线收敛。

---

## 接线点（推荐位置）

### 接入点 A：`post_process` — 最自然

```
core/pipeline.py → post_process()
```

- 已在 `uid_lock` 临界区内，符合 WriteEnvelope 并发要求。
- 已有 `_scope`, `reply`, `context` 可读，能提取情绪强度、亲密倾向。
- 在 `capture_turn` 写完 short_term 之后、`_mt.load` / `_episodic` 之前插入。

```python
# 伪代码，接线时补全
if scope and reality_signals_available(context):
    envelope = stamp_user_chat(scope.uid)          # NOT stamp_debug()
    await integrate_impression_and_save(
        uid=scope.uid,
        char_id=scope.char_id,
        envelope=envelope,
        inp=ImpressionInput(
            emotion_intensity=extract_emotion_intensity(context),
            intimacy_signal=extract_intimacy(context),
        ),
    )
    if reality_event := map_to_reality_event(context):
        await integrate_event_and_save(
            uid=scope.uid,
            char_id=scope.char_id,
            envelope=envelope,
            event=reality_event,
        )
```

### 接入点 B：`fixation_pipeline` — 备选

- 已读取 identity/fixation 状态，能用 fixation 变化驱动 SEEK_COMPANIONSHIP。
- 但 fixation_pipeline 不在 uid_lock 内 → 需额外同步或移到 post_process。
- **推荐先走 A，B 留作事件源扩展。**

---

## RealityEventType 映射表（待定，参考草案）

| 对话信号 | RealityEventType | 触发阈值 |
|---|---|---|
| 用户主动发起陪伴类请求 | `SEEK_COMPANIONSHIP` | 关键词/intent 检测 |
| 叶瑄回复有情绪安抚 | `RECEIVED_COMFORT` | emotion_label ∈ 安抚集合 |
| 超过 N 小时无对话 | `NO_INTERACTION` | 由 scheduler 触发，不走 post_process |
| 身体类描写 | `RECEIVED_PHYSICAL_TOUCH` | 需场景 tag 判断 |

> **施工前必须定稿**：`RealityEventType` 是枚举，新增值需同步更新 `_assert_allowed_source` 守卫。

---

## ImpressionInput 字段映射（待定）

```python
@dataclass
class ImpressionInput:
    emotion_intensity: float   # 0–1，从 build_prompt context 的情绪标签推断
    intimacy_signal: float     # 0–1，来自 intimacy_tendency HUD 字段或 dream_context
```

- `emotion_intensity` 可从 `context.get("emotion_label")` 做静态 lookup（安抚类→高，冷淡类→低）。
- `intimacy_signal` 可复用 `mid_term` 里已提取的亲密度字段。

---

## 并发与锁

- **必须在 `uid_lock` 内**：`post_process` 已在 `async with uid_lock:` 块内，可直接调用。
- 如改为独立 task，需自行 `async with uid_lock:`，且不能与 `capture_turn` 并发。
- `user_hidden_state_store.load_hidden_state` / `save_hidden_state` 已是原子文件写，但多个并发 save 仍有覆盖风险。

---

## WriteEnvelope 约束

```python
# 允许的 source
envelope = stamp_user_chat(scope.uid)    # ✓ source=reality_behavior

# 不允许
envelope = stamp_debug()                 # ✗ _assert_not_long_term 会 raise
envelope = stamp_trigger()               # ✗ trigger 不是用户对话来源
```

- `_assert_not_long_term` 守卫会阻止 `integrate_event` 写 baseline 和 body_memory（这是设计意图）。
- 只有 `integrate_body_cue_and_save` 可以写 body_memory，且需 `stamp_user_chat`。

---

## Source 守卫说明

```python
# user_hidden_state_integrator.py 内部
def _assert_allowed_source(envelope: WriteEnvelope) -> None:
    if envelope.source not in ALLOWED_REALITY_SOURCES:
        raise ValueError(f"Disallowed source: {envelope.source}")
```

- `ALLOWED_REALITY_SOURCES` 目前只含 `reality_behavior`。
- 接线前确认枚举值 `UpdateSource.REALITY_BEHAVIOR` 已在 `UpdateSource` 中定义。

---

## 施工检查清单（接线时用）

- [ ] 定稿 `RealityEventType` 映射表，补全枚举值
- [ ] 定稿 `ImpressionInput` 提取逻辑
- [ ] 在 `post_process` `uid_lock` 块内插入调用
- [ ] 使用 `stamp_user_chat(scope.uid)` 构造 envelope
- [ ] 运行 `scripts/audit_hidden_state.py` 前后对比，确认 `last_update_source` 出现 `reality_behavior`
- [ ] 运行全量测试（重点：`tests/test_n2_fetch_context_side_effects.py`、`tests/test_n2b_mood_envelope_lock.py`）
- [ ] 更新 `docs/known-issues.md §H1` 状态为 `resolved`

---

## 不要做的事

- ❌ 不接 `integrate_body_cue_and_save`（时机未定，信号噪声高）
- ❌ 不在 fixation_pipeline 外部裸调 integrator（uid_lock 风险）
- ❌ 不用 `stamp_debug()` 或 `stamp_trigger()` — 会绕过 source 守卫意图

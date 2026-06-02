"""
tests/test_strip_render_tags.py — Task B: <say> 标签收口

覆盖场景：
  1. strip_render_tags: <say>/<thought>/<narration> 被完整剥离
  2. strip_render_tags: 嵌套/多处标签一次性清理
  3. strip_render_tags: 无标签纯文本原样返回
  4. QQ fanout 收到纯文本（无 <say>）
  5. mobile fanout 收到纯文本（无 <say>）
  6. memory/post_process 收到纯文本（无 <say>）
  7. desktop channel_message 仍收到完整原文（含标签，渲染侧负责解析）
  8. desktop message_segments 仍保留原有 NMP 解析行为（say segment 存在）
  9. test_message_segments_plain_text 回归：无标签文本行为不变
"""

import asyncio

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

class _Channel:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.is_active = True
        self.sent = []

    async def send(self, content, user_id, behavior=None, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append(content)


class _CapturePipeline:
    """Records the reply text passed to post_process for assertions."""

    def __init__(self):
        self.captured_reply: str | None = None

    async def post_process(self, uid, content, reply, **kwargs):
        self.captured_reply = reply
        return {"turn_id": "t1", "critical_written": True, "emotion": "neutral"}


async def _reset_channels():
    from channels import registry
    registry._channels = {}


# ═══════════════════════════════════════════════════════════════════════════════
# 1–3. strip_render_tags unit tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_strip_say_tag():
    from core.response_processor import strip_render_tags
    assert strip_render_tags("<say>你好</say>") == "你好"


def test_strip_thought_tag():
    from core.response_processor import strip_render_tags
    assert strip_render_tags("<thought>内心想法</thought>") == "内心想法"


def test_strip_narration_tag():
    from core.response_processor import strip_render_tags
    assert strip_render_tags("<narration>旁白文字</narration>") == "旁白文字"


def test_strip_mixed_tags():
    from core.response_processor import strip_render_tags
    text = "<say>说话</say><narration>旁白</narration><thought>思考</thought>"
    result = strip_render_tags(text)
    assert "<say>" not in result
    assert "<narration>" not in result
    assert "<thought>" not in result
    assert "说话" in result
    assert "旁白" in result
    assert "思考" in result


def test_strip_plain_text_unchanged():
    from core.response_processor import strip_render_tags
    raw = "普通的一句话，没有任何标签。"
    assert strip_render_tags(raw) == raw


def test_strip_nmp_do_env_feel():
    from core.response_processor import strip_render_tags
    text = "她说：<say>你好</say><do>点头</do><env>室内很暖</env><feel>温暖</feel>"
    result = strip_render_tags(text)
    assert "<" not in result
    assert ">" not in result
    assert "你好" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. QQ fanout 不含 <say>
# ═══════════════════════════════════════════════════════════════════════════════

async def test_qq_fanout_strips_say_tags():
    """QQ channel 收到的文本不含 <say> 标签。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    qq_ch = _Channel("qq")
    registry.register(qq_ch)

    await record_assistant_turn(
        assistant_text="她说：<say>你好</say>",
        uid="uid1",
        source=TurnSource.USER_CHAT,
        user_text="hello",
        fanout="qq",
        pipeline=_CapturePipeline(),
    )

    assert len(qq_ch.sent) == 1
    assert "<say>" not in qq_ch.sent[0]
    assert "</say>" not in qq_ch.sent[0]
    assert "你好" in qq_ch.sent[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. mobile fanout 不含 <say>
# ═══════════════════════════════════════════════════════════════════════════════

async def test_mobile_fanout_strips_say_tags():
    """mobile channel 收到的文本不含 <say> 标签。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    mobile_ch = _Channel("mobile")
    registry.register(mobile_ch)

    await record_assistant_turn(
        assistant_text="<say>今天天气不错。</say>",
        uid="uid2",
        source=TurnSource.TRIGGER,
        trigger_name="morning_greeting",
        fanout="mobile",
        pipeline=_CapturePipeline(),
    )

    assert len(mobile_ch.sent) == 1
    assert "<say>" not in mobile_ch.sent[0]
    assert "今天天气不错" in mobile_ch.sent[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. memory/post_process 收到纯文本（无 <say>）
# ═══════════════════════════════════════════════════════════════════════════════

async def test_memory_text_stripped_of_say_tags():
    """post_process 收到的 reply 参数不含 <say> 标签。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    pipeline = _CapturePipeline()

    await record_assistant_turn(
        assistant_text="<say>记住我。</say>",
        uid="uid3",
        source=TurnSource.USER_CHAT,
        user_text="test",
        fanout=[],
        pipeline=pipeline,
    )

    assert pipeline.captured_reply is not None
    assert "<say>" not in pipeline.captured_reply
    assert "记住我" in pipeline.captured_reply


async def test_memory_text_stripped_of_multiple_tags():
    """post_process 收到的 reply 中 <say>/<do>/<feel>/<env> 全部被剥离。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    pipeline = _CapturePipeline()
    raw = "<say>说话</say><do>动作</do><feel>感受</feel><env>环境</env>"

    await record_assistant_turn(
        assistant_text=raw,
        uid="uid4",
        source=TurnSource.USER_CHAT,
        user_text="test",
        fanout=[],
        pipeline=pipeline,
    )

    reply = pipeline.captured_reply
    assert reply is not None
    assert "<" not in reply
    assert ">" not in reply


# ═══════════════════════════════════════════════════════════════════════════════
# 7. desktop channel_message 收到完整原文（含标签）
# ═══════════════════════════════════════════════════════════════════════════════

async def test_desktop_fanout_receives_full_text(monkeypatch):
    """desktop channel 收到的 assistant_text 保持原样（NMP 标签完整）。"""
    from channels import registry
    from channels.desktop import DesktopChannel
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()

    push_msg_calls: list[dict] = []

    async def fake_push_message(content, msg_id=None):
        push_msg_calls.append({"content": content, "msg_id": msg_id})
        return True

    async def fake_push_segments(*args, **kwargs):
        return True

    monkeypatch.setattr("channels.desktop_ws.is_connected", lambda: True)
    monkeypatch.setattr("channels.desktop_ws.push_message", fake_push_message)
    monkeypatch.setattr("channels.desktop_ws.push_segments", fake_push_segments)

    registry.register(DesktopChannel())
    raw = "她说：<say>你好</say>"

    await record_assistant_turn(
        assistant_text=raw,
        uid="uid5",
        source=TurnSource.USER_CHAT,
        user_text="hello",
        fanout="desktop",
        pipeline=_CapturePipeline(),
    )

    assert len(push_msg_calls) == 1
    # Desktop channel_message preserves original text with tags
    assert "<say>" in push_msg_calls[0]["content"]
    assert "你好" in push_msg_calls[0]["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. desktop message_segments 仍保留 NMP 解析行为
# ═══════════════════════════════════════════════════════════════════════════════

async def test_desktop_message_segments_say_segment_preserved(monkeypatch):
    """desktop message_segments 仍推送 say segment，NMP 渲染行为不被破坏。"""
    from channels import registry
    from channels.desktop import DesktopChannel
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()

    push_seg_calls: list[dict] = []

    async def fake_push_message(content, msg_id=None):
        return True

    async def fake_push_segments(content, segments, msg_id=None):
        push_seg_calls.append({"content": content, "segments": segments})
        return True

    monkeypatch.setattr("channels.desktop_ws.is_connected", lambda: True)
    monkeypatch.setattr("channels.desktop_ws.push_message", fake_push_message)
    monkeypatch.setattr("channels.desktop_ws.push_segments", fake_push_segments)

    registry.register(DesktopChannel())

    await record_assistant_turn(
        assistant_text="<say>你好</say>",
        uid="uid6",
        source=TurnSource.USER_CHAT,
        user_text="hello",
        fanout="desktop",
        pipeline=_CapturePipeline(),
    )

    assert len(push_seg_calls) == 1
    say_segs = [s for s in push_seg_calls[0]["segments"] if s["type"] == "say"]
    assert len(say_segs) == 1
    assert say_segs[0]["text"] == "你好"

    # content (plain) has no tags
    assert "<say>" not in push_seg_calls[0]["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 回归：无标签纯文本行为不变（test_message_segments_plain_text 对应场景）
# ═══════════════════════════════════════════════════════════════════════════════

async def test_plain_text_memory_unchanged():
    """无标签纯文本时，post_process 收到的 reply 与原文相同（strip 无副作用）。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    pipeline = _CapturePipeline()
    raw = "普通的一句话，没有任何标签。"

    await record_assistant_turn(
        assistant_text=raw,
        uid="uid7",
        source=TurnSource.USER_CHAT,
        user_text="hi",
        fanout=[],
        pipeline=pipeline,
    )

    assert pipeline.captured_reply == raw


async def test_plain_text_qq_fanout_unchanged():
    """无标签纯文本时，QQ channel 收到文本与原文相同。"""
    from channels import registry
    from core.turn_sink import TurnSource, record_assistant_turn

    await _reset_channels()
    qq_ch = _Channel("qq")
    registry.register(qq_ch)

    raw = "普通的一句话。"
    await record_assistant_turn(
        assistant_text=raw,
        uid="uid8",
        source=TurnSource.USER_CHAT,
        user_text="hi",
        fanout="qq",
        pipeline=_CapturePipeline(),
    )

    assert qq_ch.sent[0] == raw

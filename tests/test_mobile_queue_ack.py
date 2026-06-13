import asyncio
import json
import time


async def _push(channel, count: int) -> None:
    for index in range(count):
        await channel.send(f"message-{index + 1}", "owner", msg_id=f"turn-{index + 1}")


async def test_poll_retains_until_ack_and_ack_removes_prefix(sandbox):
    from channels.mobile import MobileChannel

    channel = MobileChannel()
    await _push(channel, 3)

    messages = await channel.poll(after=None, limit=20)
    stored = json.loads(sandbox.mobile_queue().read_text(encoding="utf-8"))

    assert len(messages) == 3
    assert len(stored) == 3
    assert [item["seq"] for item in messages] == sorted(item["seq"] for item in messages)

    remaining = await channel.ack(messages[1]["seq"])
    after_ack = await channel.poll(after=None, limit=20)

    assert remaining == 1
    assert [item["id"] for item in after_ack] == ["turn-3"]


async def test_poll_after_returns_only_newer_items(sandbox):
    from channels.mobile import MobileChannel

    channel = MobileChannel()
    await _push(channel, 3)
    messages = await channel.poll(after=None, limit=20)

    newer = await channel.poll(after=messages[1]["seq"], limit=20)

    assert [item["id"] for item in newer] == ["turn-3"]


async def test_concurrent_push_assigns_unique_monotonic_sequences(sandbox):
    from channels.mobile import MobileChannel

    channel = MobileChannel()
    await asyncio.gather(
        *(channel.send(f"message-{index}", "owner", msg_id=f"turn-{index}") for index in range(40))
    )

    messages = await channel.poll(after=None, limit=50)
    sequences = [item["seq"] for item in messages]

    assert len(sequences) == 40
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == 40


async def test_sequence_remains_monotonic_after_full_ack(sandbox):
    from channels.mobile import MobileChannel

    channel = MobileChannel()
    await channel.send("first", "owner", msg_id="turn-first")
    first = (await channel.poll(after=None, limit=20))[0]
    await channel.ack(first["seq"])

    await channel.send("second", "owner", msg_id="turn-second")
    second = (await channel.poll(after=None, limit=20))[0]

    assert second["seq"] > first["seq"]


async def test_legacy_queue_items_receive_sequences_before_poll(sandbox):
    from channels.mobile import MobileChannel
    from core.safe_write import safe_write_json

    safe_write_json(
        sandbox.mobile_queue(),
        [
            {"id": "legacy-1", "content": "one", "user_id": "owner", "timestamp": time.time()},
            {"id": "legacy-2", "content": "two", "user_id": "owner", "timestamp": time.time()},
        ],
    )
    channel = MobileChannel()

    messages = await channel.poll(after=None, limit=20)
    await channel.ack(messages[-1]["seq"])
    await channel.send("new", "owner", msg_id="turn-new")
    new_message = (await channel.poll(after=None, limit=20))[0]

    assert [item["seq"] for item in messages] == [1, 2]
    assert new_message["seq"] == 3


async def test_queue_prunes_by_ttl_and_capacity(sandbox, monkeypatch):
    import channels.mobile as mobile_module
    from channels.mobile import MobileChannel
    from core.safe_write import safe_write_json

    monkeypatch.setattr(mobile_module, "_QUEUE_MAX_ITEMS", 2)
    safe_write_json(
        sandbox.mobile_queue(),
        [
            {
                "id": "expired",
                "seq": 1,
                "content": "expired",
                "user_id": "owner",
                "timestamp": time.time() - mobile_module._QUEUE_MAX_AGE_SECONDS - 1,
            }
        ],
    )
    safe_write_json(sandbox.mobile_queue_seq(), {"next_seq": 2})
    channel = MobileChannel()

    await _push(channel, 3)
    messages = await channel.poll(after=None, limit=20)

    assert [item["id"] for item in messages] == ["turn-2", "turn-3"]


async def test_mobile_router_poll_cursor_and_ack_remaining(sandbox, monkeypatch):
    from admin.routers import mobile as mobile_router
    from channels.mobile import MobileChannel

    channel = MobileChannel()
    await _push(channel, 3)
    monkeypatch.setattr(mobile_router, "_get_mobile_channel", lambda: channel)

    response = await mobile_router.mobile_poll(after=None, limit=20, wait=0, auth=True)
    ack_response = await mobile_router.mobile_ack(
        {"ack_seq": response["messages"][1]["seq"]},
        auth=True,
    )

    assert response["cursor"] == response["messages"][-1]["seq"]
    assert all("seq" in item for item in response["messages"])
    assert ack_response == {"ok": True, "remaining": 1}

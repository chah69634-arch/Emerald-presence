from core.memory import short_term


def _entry(role, content, ts, turn_id=None):
    item = {"role": role, "content": content, "timestamp": ts}
    if turn_id is not None:
        item["_turn_id"] = turn_id
    return item


def test_group_turns_scores_and_load_for_prompt_selection(monkeypatch):
    history = [
        _entry("user", "", 1, "t_low"),
        _entry("assistant", "（点头）", 2, "t_low"),
        _entry("user", "我昨天在杭州圣塞西尔学院跑 Claude 代码，2026-05-24 还记得吗？我真的好累。", 3, "t_high"),
        _entry("assistant", "记得。你是在调 short_term 的读路径，还提到了 Obsidian 日记。", 4, "t_high"),
        _entry("assistant", "（scheduler 触发）你已经坐了很久，起来喝口水。", 5, "t_trigger"),
        _entry("user", "legacy 用户说：之前在上海医院做检查，晚上 8 点还没吃饭。", 6),
        _entry("assistant", "legacy 助手回应：我记着这件事。", 7),
        _entry("assistant", "legacy 孤立 assistant。", 8),
        _entry("user", "近场第一轮。", 9, "t_near_1"),
        _entry("assistant", "近场第一轮回复。", 10, "t_near_1"),
        _entry("user", "近场第二轮。", 11, "t_near_2"),
        _entry("assistant", "近场第二轮回复。", 12, "t_near_2"),
    ]

    groups = short_term._group_turns(history)
    assert [[m.get("_turn_id") for m in group] for group in groups] == [
        ["t_low", "t_low"],
        ["t_high", "t_high"],
        ["t_trigger"],
        [None, None],
        [None],
        ["t_near_1", "t_near_1"],
        ["t_near_2", "t_near_2"],
    ]
    assert [m["role"] for m in groups[2]] == ["assistant"]
    assert [m["role"] for m in groups[3]] == ["user", "assistant"]

    low_score, _ = short_term._score_turn_group(groups[0])
    high_score, _ = short_term._score_turn_group(groups[1])
    assert high_score > low_score
    capped_score, capped_parts = short_term._score_turn_group([
        _entry(
            "user",
            "我昨天在杭州圣塞西尔学院跑 Claude 代码，2026-05-24 还记得吗？其实我好累又想哭。",
            13,
            "t_cap",
        ),
        _entry(
            "assistant",
            "记得，你说过这个项目、系统、模型和文档都卡住了，但你还是一直撑着。",
            14,
            "t_cap",
        ),
    ])
    assert capped_score <= short_term.TURN_SCORE_CAP
    assert any(value > 0 for value in capped_parts.values())

    monkeypatch.setattr(short_term, "load", lambda user_id, *, char_id="yexuan": [dict(item) for item in history])
    selected = short_term.load_for_prompt("u_weight", budget_rounds=4, near_k=2)

    selected_turn_ids = [m.get("_turn_id") for m in selected]
    assert "t_near_1" in selected_turn_ids
    assert "t_near_2" in selected_turn_ids
    assert "t_high" in selected_turn_ids
    assert "t_low" not in selected_turn_ids

    selected_timestamps = [m["timestamp"] for m in selected]
    assert selected_timestamps == sorted(selected_timestamps)

    for turn_id in {"t_high", "t_near_1", "t_near_2"}:
        assert selected_turn_ids.count(turn_id) == 2


def test_group_turns_keeps_multiple_assistant_speakers_in_one_turn():
    history = [
        {**_entry("user", "大家觉得呢？", 1, "t_group"), "speaker_id": "owner"},
        {**_entry("assistant", "我先说。", 2, "t_group"), "speaker_id": "yexuan"},
        {**_entry("assistant", "我补一句。", 3, "t_group"), "speaker_id": "hongcha"},
    ]

    groups = short_term._group_turns(history)

    assert len(groups) == 1
    assert [item["speaker_id"] for item in groups[0]] == ["owner", "yexuan", "hongcha"]


def test_score_turn_group_rewards_assistant_speaker_diversity():
    one_speaker = [
        {**_entry("assistant", "同一句。", 1, "t1"), "speaker_id": "yexuan"},
        {**_entry("assistant", "同一句。", 2, "t1"), "speaker_id": "yexuan"},
    ]
    two_speakers = [
        {**_entry("assistant", "同一句。", 1, "t2"), "speaker_id": "yexuan"},
        {**_entry("assistant", "同一句。", 2, "t2"), "speaker_id": "hongcha"},
    ]

    one_score, one_parts = short_term._score_turn_group(one_speaker)
    two_score, two_parts = short_term._score_turn_group(two_speakers)

    assert one_parts["speaker_diversity"] == 0
    assert two_parts["speaker_diversity"] > 0
    assert two_score > one_score

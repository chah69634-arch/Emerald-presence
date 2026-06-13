import json


def test_append_defaults_speaker_ids_and_allows_multiple_assistants(sandbox):
    from core.memory import short_term

    uid = "speaker-defaults"
    turn_id = "turn-group"

    assert short_term.append(uid, "user", "大家好", turn_id=turn_id, char_id="yexuan")
    assert short_term.append(uid, "assistant", "在。", turn_id=turn_id, char_id="yexuan")
    assert short_term.append(
        uid,
        "assistant",
        "我也在。",
        turn_id=turn_id,
        char_id="yexuan",
        speaker_id="hongcha",
    )
    # Same speaker may speak again in the same stage turn when content differs.
    assert short_term.append(uid, "assistant", "再补一句。", turn_id=turn_id, char_id="yexuan")
    # Exact duplicate is idempotent.
    assert short_term.append(uid, "assistant", "再补一句。", turn_id=turn_id, char_id="yexuan")

    history = short_term.load(uid, char_id="yexuan")

    assert [item["speaker_id"] for item in history] == ["owner", "yexuan", "hongcha", "yexuan"]
    assert [item["content"] for item in history] == ["大家好", "在。", "我也在。", "再补一句。"]


def test_load_projects_speaker_ids_for_legacy_entries_without_rewriting_disk(sandbox):
    from core.memory import short_term
    from core.safe_write import safe_write_json

    uid = "speaker-legacy"
    path = sandbox.user_memory_root(uid, char_id="hongcha") / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = [
        {"role": "user", "content": "你好", "timestamp": 1},
        {"role": "assistant", "content": "在。", "timestamp": 2},
    ]
    safe_write_json(path, raw)

    loaded = short_term.load(uid, char_id="hongcha")
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert [item["speaker_id"] for item in loaded] == ["owner", "hongcha"]
    assert all("speaker_id" not in item for item in stored)


def test_disk_trim_keeps_complete_multi_speaker_turn(sandbox, monkeypatch):
    from core.memory import short_term

    monkeypatch.setattr(
        short_term,
        "get_config",
        lambda: {"memory": {"short_term_disk_rounds": 1, "short_term_rounds": 1}},
    )
    uid = "speaker-trim"

    short_term.append(uid, "user", "旧问题", turn_id="old", char_id="yexuan")
    short_term.append(uid, "assistant", "旧回答", turn_id="old", char_id="yexuan")
    short_term.append(uid, "user", "新问题", turn_id="new", char_id="yexuan")
    short_term.append(uid, "assistant", "回答 A", turn_id="new", char_id="yexuan")
    short_term.append(
        uid,
        "assistant",
        "回答 B",
        turn_id="new",
        char_id="yexuan",
        speaker_id="hongcha",
    )

    history = short_term.load(uid, char_id="yexuan")

    assert len(history) == 3
    assert {item["_turn_id"] for item in history} == {"new"}
    assert [item["speaker_id"] for item in history] == ["owner", "yexuan", "hongcha"]


def test_get_history_max_turns_keeps_complete_multi_speaker_turn(sandbox):
    from core.memory import short_term

    uid = "speaker-get-history"
    for turn_id in ("old", "new"):
        short_term.append(uid, "user", turn_id, turn_id=turn_id, char_id="yexuan")
        short_term.append(uid, "assistant", f"{turn_id}-a", turn_id=turn_id, char_id="yexuan")
        short_term.append(
            uid,
            "assistant",
            f"{turn_id}-b",
            turn_id=turn_id,
            char_id="yexuan",
            speaker_id="hongcha",
        )

    history = short_term.get_history(uid, max_turns=1, char_id="yexuan")

    assert len(history) == 3
    assert {item["_turn_id"] for item in history} == {"new"}


def test_prompt_boundary_strips_local_speaker_metadata():
    from core.prompt_layer import sanitize_messages

    source = [{
        "role": "assistant",
        "content": "在。",
        "speaker_id": "yexuan",
        "timestamp": 123,
        "_turn_id": "turn-1",
        "_layer": "9_history",
    }]

    assert sanitize_messages(source) == [{"role": "assistant", "content": "在。"}]
    assert source[0]["speaker_id"] == "yexuan"

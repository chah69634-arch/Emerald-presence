"""
用户画像模块
存储从对话中提炼出的结构化用户信息
持久化到 data/profiles/{user_id}.json
"""

import json
import logging
import re
from pathlib import Path

from core.config_loader import get_config, _char_name
from core.error_handler import log_error
from core.sandbox import get_paths, safe_user_id

logger = logging.getLogger(__name__)
_CHAR = _char_name()

# 画像字段的默认结构
_DEFAULT_PROFILE = {
    "name": None,           # 真实姓名/常用称呼
    "location": None,       # 所在地
    "pets": None,           # 宠物
    "interests": None,      # 兴趣爱好
    "occupation": None,     # 职业/学校
    "important_facts": [],  # 其他重要事实（列表）
}


def _profile_read_path(user_id: str, *, char_id: str = "yexuan") -> Path:
    uid = safe_user_id(user_id)
    return get_paths().user_memory_root(uid, char_id=char_id) / "profile.json"


def _profile_write_path(user_id: str, *, char_id: str = "yexuan") -> Path:
    """写路径：始终写新布局。"""
    uid = safe_user_id(user_id)
    p = get_paths().user_memory_root(uid, char_id=char_id) / "profile.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load(user_id: str) -> dict:
    """
    读取用户画像，文件不存在时返回空模板
    """
    path = _profile_read_path(user_id)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 用默认模板填充缺失字段，保证结构完整
            merged = dict(_DEFAULT_PROFILE)
            merged.update(data)
            return merged
    except Exception as e:
        log_error("user_profile.load", e)
    return dict(_DEFAULT_PROFILE)


async def _compress_facts(facts: list) -> list:
    """
    调用 LLM 对 important_facts 列表做合并去重，
    返回不超过 30 条的精简版本。失败时原样返回。
    """
    try:
        from core import llm_client
        import json as _json

        prompt = (
            "以下是用户的重要事实列表，请整理精简。规则：\n"
            "1. 语义相同或高度相似的条目只保留一条，措辞最准确的那条\n"
            "2. 以下类型直接删除：测试AI行为的记录、单次临时状态、对话玩笑、已在name/location/pets/interests/occupation字段存储的信息\n"
            "3. 输出不超过25条\n"
            "只输出JSON数组，不要其他内容：\n"
            + _json.dumps(facts, ensure_ascii=False)
        )
        raw = await llm_client.chat([{"role": "user", "content": prompt}], max_tokens_override=2000)
        raw = raw.strip()
        # 清理各种markdown代码块格式
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        raw = raw.strip()
        # 提取JSON数组
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group()
        else:
            # 尝试补全截断的JSON数组
            if raw.startswith("[") and not raw.endswith("]"):
                last_quote = raw.rfind('"')
                if last_quote > 0:
                    raw = raw[:last_quote+1] + "]"
        compressed = _json.loads(raw)
        if isinstance(compressed, list):
            logger.info(
                f"[user_profile] important_facts 已合并压缩：{len(facts)} → {len(compressed)} 条"
            )
            return compressed
    except Exception as e:
        log_error("user_profile._compress_facts", e)
    return facts


async def update(user_id: str, new_facts: dict):
    """
    合并更新用户画像，不覆盖已有非空值

    new_facts 中 important_facts 列表会去重追加；
    追加后若总数超过 50 条，触发 LLM 压缩到 30 条以内。
    其他字段只在原值为 None 时更新
    """
    profile = load(user_id)

    for key, value in new_facts.items():
        if key == "important_facts":
            # 列表字段：去重追加
            existing = profile.get("important_facts") or []
            if isinstance(value, list):
                for item in value:
                    if item and item not in existing:
                        existing.append(item)
            elif value and value not in existing:
                existing.append(value)

            # 超过 50 条时触发 LLM 合并压缩
            if len(existing) > 30:
                logger.info(
                    f"[user_profile] important_facts 已达 {len(existing)} 条，触发 LLM 压缩"
                )
                existing = await _compress_facts(existing)

            profile["important_facts"] = existing
        else:
            # 其他字段：只在原值为空时更新
            if not profile.get(key) and value:
                profile[key] = value

    _save(user_id, profile)


async def extract_and_update(user_id: str, recent_messages: list[dict]):
    """
    用 LLM 从最近对话中提取新的用户信息，并更新画像
    应每 N 轮调用一次（N = summary_every_n_rounds）

    LLM 被要求只返回 JSON，不输出其他内容
    """
    if not recent_messages:
        return

    # 把消息列表转换成可读文本
    conv_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
        for m in recent_messages[-10:]  # 只取最近10条，省token
    )

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是一个信息提取助手。请从下面的对话中提取用户的个人信息。\n"
                "只返回 JSON 对象，不要输出任何其他内容。\n"
                "JSON 格式：\n"
                '{"name": null或字符串, "location": null或字符串, "pets": null或字符串, "interests": null或字符串, "occupation": null或字符串, "important_facts": [字符串列表]}\n'
                "important_facts 只记录稳定的、有意义的个人事实，例如：性格特点、生活习惯、重要经历、身体状况（包括精神状态）。\n"
                "绝对不要记录：用户测试AI功能的行为、单次询问某件事、临时状态、对话中的玩笑或表情包、已经在其他字段记录的信息。\n"
                "没有提到的字段填 null。"
            ),
        },
        {
            "role": "user",
            "content": f"对话内容：\n{conv_text}",
        },
    ]

    try:
        from core import llm_client
        import json as _json

        raw = await llm_client.chat(prompt_messages)
        # 清理可能的 markdown 代码块
        raw = raw.strip().strip("```json").strip("```").strip()
        raw = (raw
               .replace("“", '"').replace("”", '"')
               .replace("‘", "'").replace("’", "'"))
        new_facts = _json.loads(raw)
        from core.integrity_check import check_profile
        _issues = check_profile(new_facts)
        if _issues:
            logger.warning(f"[user_profile] 内容未通过规则纠察，拒绝写入: {_issues}")
            return
        await update(user_id, new_facts)
        logger.info(f"[user_profile] 用户 {user_id} 画像已更新")
    except Exception as e:
        log_error("user_profile.extract_and_update", e)


def _save(user_id: str, profile: dict):
    """把画像写回磁盘"""
    path = _profile_write_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("user_profile._save", e)


def save(user_id: str, profile: dict):
    """公开接口：直接将 profile 写回磁盘（admin 覆盖编辑用）"""
    _save(user_id, profile)


def clear(user_id: str):
    """清空用户画像（admin 用）"""
    _save(user_id, dict(_DEFAULT_PROFILE))


# ─── 好感度系统（已冻结） ────────────────────────────────────────────────────────────────

_AFFECTION_LEVELS = [
    (0,   99,   "陌生人",   f"{_CHAR}对她还不太了解"),
    (100, 299,  "普通朋友", f"{_CHAR}对她有些印象"),
    (300, 499,  "好朋友",   f"{_CHAR}很高兴认识她"),
    (500, 699,  "亲密朋友", f"{_CHAR}很珍惜和她在一起的时光"),
    (700, 899,  "挚友",     f"{_CHAR}对她有深厚的情感"),
    (900, 1000, "灵魂伴侣", f"{_CHAR}认为她是最重要的人"),
]


def get_affection(user_id: str) -> int:
    """读取用户好感度，默认 0"""
    path = _profile_read_path(user_id)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("affection", 0))
    except Exception as e:
        log_error("user_profile.get_affection", e)
    return 0


def add_affection(user_id: str, delta: int):
    """增减好感度，结果限制在 0-1000"""
    read_path = _profile_read_path(user_id)
    write_path = _profile_write_path(user_id)
    try:
        if read_path.exists():
            with open(read_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = dict(_DEFAULT_PROFILE)
        current = int(data.get("affection", 0))
        data["affection"] = max(0, min(1000, current + delta))
        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("user_profile.add_affection", e)


def set_affection(user_id: str, value: int):
    """直接设置好感度（管理员用）"""
    read_path = _profile_read_path(user_id)
    write_path = _profile_write_path(user_id)
    try:
        if read_path.exists():
            with open(read_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = dict(_DEFAULT_PROFILE)
        data["affection"] = max(0, min(1000, int(value)))
        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("user_profile.set_affection", e)


def get_affection_level(user_id: str) -> dict:
    """返回好感度等级信息：{value, label, description}"""
    value = get_affection(user_id)
    for lo, hi, label, desc in _AFFECTION_LEVELS:
        if lo <= value <= hi:
            return {"value": value, "label": label, "description": desc}
    return {"value": value, "label": "灵魂伴侣", "description": _AFFECTION_LEVELS[-1][3]}


# ─── 生理期 ────────────────────────────────────────────────────────────────────

def get_period_info(user_id: str) -> dict:
    """读取生理期信息，返回包含 last_period_date 字段的字典"""
    profile = load(user_id)
    return {"last_period_date": profile.get("last_period_date")}


def set_period_date(user_id: str, date_str: str):
    """设置上次生理期日期（格式：YYYY-MM-DD）"""
    read_path = _profile_read_path(user_id)
    write_path = _profile_write_path(user_id)
    try:
        if read_path.exists():
            with open(read_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = dict(_DEFAULT_PROFILE)
        data["last_period_date"] = date_str
        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("user_profile.set_period_date", e)


class UserProfile:
    """用户画像类，封装模块级函数，供外部按类方式导入使用"""

    def load(self, user_id: str) -> dict:
        return load(user_id)

    async def update(self, user_id: str, new_facts: dict):
        await update(user_id, new_facts)

    async def extract_and_update(self, user_id: str, recent_messages: list[dict]):
        await extract_and_update(user_id, recent_messages)

    def save(self, user_id: str, profile: dict):
        save(user_id, profile)

    def clear(self, user_id: str):
        clear(user_id)

    def get_affection(self, user_id: str) -> int:
        return get_affection(user_id)

    def add_affection(self, user_id: str, delta: int):
        add_affection(user_id, delta)

    def set_affection(self, user_id: str, value: int):
        set_affection(user_id, value)

    def get_affection_level(self, user_id: str) -> dict:
        return get_affection_level(user_id)

"""
世界书（Lore Book）引擎
扫描消息中的关键词，命中时注入对应的世界观描述

数据来源（两个都会加载，取并集）：
  1. data/lorebook.yaml          — admin 面板可编辑的独立世界书文件
  2. 角色卡 JSON 的 world_book 字段 — SillyTavern 格式的内嵌世界书

YAML 条目格式：
  keyword: ["圣塞西尔", "学院"]   ← 列表字段名是 keyword（单数）
  content: "..."
  enabled: true
  regex: false                   ← true 时 keyword 作为正则表达式匹配
  insertion_order: 100           ← 数字越小越靠前注入，默认 100

角色卡 world_book 条目格式：
  keywords: ["关键词1"]           ← 列表字段名是 keywords（复数）
  content: "..."
  enabled: true
"""

import logging
import re

import yaml

from core.error_handler import log_error

logger = logging.getLogger(__name__)


def _normalize_entry(entry: dict) -> dict | None:
    """
    统一条目格式：把 keyword/keywords 都统一成 keywords 字段。
    content 为空或 enabled=false 时返回 None（过滤掉）。
    同时保留 regex 和 insertion_order 字段。
    """
    if not entry.get("enabled", True):
        return None
    content = entry.get("content", "").strip()
    if not content:
        return None

    # YAML 用 keyword（列表），角色卡用 keywords（列表）
    kws = entry.get("keywords") or entry.get("keyword") or []
    if isinstance(kws, str):
        kws = [kws]
    if not kws:
        return None

    return {
        "keywords":        kws,
        "content":         content,
        "regex":           bool(entry.get("regex", False)),
        "insertion_order": int(entry.get("insertion_order", 100)),
    }


class LoreEngine:
    """
    世界书引擎

    用法：
        engine = LoreEngine()          # 不传参数
        engine.load()                  # 从 lorebook.yaml 读取
        engine.load_entries(world_book)  # 追加角色卡里的条目

        results = engine.match("用户消息文本")  # 返回命中的 content 列表
    """

    def __init__(self, world_book: list[dict] | None = None):
        # 存放所有已处理的条目（keywords 字段统一为列表）
        self.entries: list[dict] = []

        # 如果构造时传入了角色卡 world_book，先加载进去
        if world_book:
            self.load_entries(world_book)

    # ── 数据加载 ──────────────────────────────────────────────────────────────

    def load(self):
        """
        从 lorebook.yaml 读取世界书条目，追加到 self.entries。
        文件不存在时静默跳过，格式错误时记录日志后跳过。
        可多次调用（每次重置再重新加载，避免重复）
        """
        from core.sandbox import get_paths
        path = get_paths().lorebook()

        # 重置已有条目，再重新加载（防止热重载时重复）
        self.entries = []

        if not path.exists():
            logger.debug("[lore_engine] lorebook.yaml 不存在，跳过加载")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            log_error("lore_engine.load", e)
            return

        raw_entries = data.get("entries", [])
        if not isinstance(raw_entries, list):
            logger.warning("[lore_engine] lorebook.yaml entries 字段不是列表，跳过")
            return

        loaded = 0
        for entry in raw_entries:
            normalized = _normalize_entry(entry)
            if normalized:
                self.entries.append(normalized)
                loaded += 1

        logger.info(f"[lore_engine] 从 lorebook.yaml 加载了 {loaded} 条世界书条目")

    def load_entries(self, world_book: list[dict]):
        """
        追加角色卡里的世界书条目（不清空已有条目）。
        由 __init__ 或外部调用，用于合并角色卡内嵌的世界书。
        """
        added = 0
        for entry in world_book:
            normalized = _normalize_entry(entry)
            if normalized:
                self.entries.append(normalized)
                added += 1
        if added:
            logger.info(f"[lore_engine] 从角色卡追加了 {added} 条世界书条目")

    # ── 关键词匹配 ────────────────────────────────────────────────────────────

    def match(self, user_message: str, recent_messages: list[dict] | None = None) -> list[str]:
        """
        扫描用户消息（和可选的最近历史），返回命中的世界书 content 列表。

        参数:
            user_message:    当前用户消息
            recent_messages: 最近几条历史消息（可选，扩大扫描范围）

        返回:
            命中条目的 content 字符串列表，按 insertion_order 升序排列。
            无命中则返回空列表。
        """
        if not self.entries:
            return []

        # 拼接扫描文本，全部转小写做不区分大小写的普通匹配
        scan_parts = [user_message]
        if recent_messages:
            for msg in recent_messages[-5:]:
                c = msg.get("content", "")
                if c:
                    scan_parts.append(c)
        full_text = " ".join(scan_parts)
        full_text_lower = full_text.lower()

        matched: list[dict] = []  # [(insertion_order, content)]
        seen: set[str] = set()    # 去重，防止同一 content 出现两次

        for entry in self.entries:
            content = entry["content"]
            if content in seen:
                continue

            is_regex = entry.get("regex", False)
            hit = False

            for kw in entry["keywords"]:
                if is_regex:
                    try:
                        if re.search(kw, full_text, re.IGNORECASE):
                            hit = True
                            break
                    except re.error:
                        logger.warning(f"[lore_engine] 正则表达式无效：{kw!r}，跳过")
                else:
                    if kw.lower() in full_text_lower:
                        hit = True
                        break

            if hit:
                matched.append(entry)
                seen.add(content)
                logger.debug(f"[lore_engine] 条目命中（order={entry['insertion_order']}），注入世界书")

        # 按 insertion_order 升序排列（数字越小越靠前）
        matched.sort(key=lambda e: e["insertion_order"])
        return [e["content"] for e in matched]

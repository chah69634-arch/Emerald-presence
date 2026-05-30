"""
赛博宠物模块
数据持久化到 data/pet.json。

字段：
  name       — 宠物名字
  species    — 种类（猫/狗/兔子/鸟/其他）
  mood       — 心情，0-100
  hunger     — 饥饿度，0-100（越高越饿）
  affection  — 宠物好感度，0-100
  created_at — 创建时间 ISO 字符串

函数：
  get_pet()              — 读取宠物数据，不存在返回 None
  save_pet(data)         — 保存宠物数据
  update_pet(field, val) — 更新单个字段（mood/hunger/affection 自动限制 0-100）
  pet_greeting()         — 根据 mood/hunger 返回一句宠物状态描述
  get_pet_info_str()     — 供 prompt_builder 注入的一行描述，无宠物时返回 ""
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from core.config_loader import get_config, _char_name
from core.error_handler import log_error
from core.sandbox import get_paths, _TRANSITION_CHARACTER_INNER

logger = logging.getLogger(__name__)

_CLAMPED_FIELDS = {"mood", "hunger", "affection"}


# ─── 基础 CRUD ─────────────────────────────────────────────────────────────────

def get_pet() -> dict | None:
    """读取宠物数据，文件不存在或数据为空时返回 None"""
    p = get_paths().pet_file()
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data or not data.get("name"):
            return None
        return data
    except Exception as e:
        log_error("pet.get_pet", e)
        return None


def save_pet(data: dict):
    """保存宠物数据到磁盘"""
    p = get_paths().pet_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if _TRANSITION_CHARACTER_INNER:
            old = get_paths()._p("pet.json")
            with open(old, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("pet.save_pet", e)


def create_pet(name: str, species: str = "猫") -> dict:
    """创建新宠物并保存，返回宠物数据"""
    data = {
        "name":       name.strip(),
        "species":    species.strip() or "猫",
        "mood":       80,
        "hunger":     20,
        "affection":  50,
        "created_at": datetime.now().isoformat(),
    }
    save_pet(data)
    logger.info(f"[pet] 宠物 {name}（{species}）已创建")
    return data


def update_pet(field: str, value) -> dict | None:
    """
    更新宠物的单个字段，返回更新后的宠物数据。
    mood/hunger/affection 自动限制在 0-100。
    宠物不存在时返回 None。
    """
    pet = get_pet()
    if pet is None:
        return None
    if field in _CLAMPED_FIELDS:
        value = max(0, min(100, int(value)))
    pet[field] = value
    save_pet(pet)
    return pet


# ─── 状态描述 ──────────────────────────────────────────────────────────────────

def pet_greeting(pet: dict | None = None) -> str:
    """
    根据 mood 和 hunger 返回一句宠物状态描述。
    不传参时自动读取。
    """
    if pet is None:
        pet = get_pet()
    if not pet:
        return ""

    species = pet.get("species", "猫")
    name    = pet.get("name", "小东西")
    mood    = int(pet.get("mood",   80))
    hunger  = int(pet.get("hunger", 20))

    # 优先级：饿 > 心情差 > 正常
    if hunger >= 80:
        return f"（{name}肚子咕咕叫，眼巴巴地看着你）"
    if mood < 30:
        return f"（{name}缩在角落，不太开心）"
    if mood >= 80:
        return f"（{name}高兴地凑过来蹭你）"
    return f"（一只{species}从角落探出头）{name}：喵～"


def get_pet_info_str() -> str:
    """
    供 prompt_builder 注入的一行宠物描述。
    无宠物时返回空字符串，不注入任何内容。
    """
    pet = get_pet()
    if not pet:
        return ""
    name    = pet.get("name", "")
    species = pet.get("species", "猫")
    greeting = pet_greeting(pet)
    return f"{_char_name()}家里养了一只{species}叫{name}，{greeting}"

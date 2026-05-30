"""
自检测试：DataPaths 所有公开路径方法必须在 data_registry.REGISTRY 中有条目。
新增 DataPaths 方法忘记登记时此测试 fail，阻止静默遗漏。
"""

import inspect

import pytest

from core.sandbox import DataPaths
from core.data_registry import (
    REGISTRY,
    PathMeta,
    Durability,
    Domain,
    Scope,
    GitPolicy,
)

_VALID_DURABILITY = {"canonical", "derived", "runtime", "forensic", "archive", "authored"}
_VALID_DOMAIN     = {"reality", "dream", "shared", "character_inner"}
_VALID_SCOPE      = {"global", "per_char", "per_user", "per_char_user", "per_group"}
_VALID_GIT_POLICY = {"track", "ignore", "seed", "ignore-but-authored"}

# cleanup() 是沙盒清理动词，不返回 Path，故排除
_NON_PATH_METHODS = {"cleanup"}


def _path_method_names() -> list[str]:
    return sorted(
        name
        for name, member in inspect.getmembers(DataPaths, predicate=inspect.isfunction)
        if not name.startswith("_") and name not in _NON_PATH_METHODS
    )


def test_no_unregistered_datapaths_methods():
    """DataPaths 中每个公开路径方法都必须在 REGISTRY 中有条目。"""
    methods = _path_method_names()
    assert methods, "inspect 找不到任何 DataPaths 公开方法，检查 _path_method_names 逻辑"

    missing = [m for m in methods if m not in REGISTRY]
    if missing:
        pytest.fail(
            "以下 DataPaths 方法未在 core/data_registry.REGISTRY 中登记，请补充条目：\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


def test_no_orphan_registry_entries():
    """REGISTRY 中不应存在已删除的 DataPaths 方法（防止僵尸条目）。"""
    methods = set(_path_method_names())
    orphans = [k for k in REGISTRY if k not in methods]
    if orphans:
        pytest.fail(
            "REGISTRY 中存在 DataPaths 已不包含的孤立条目，请删除：\n"
            + "\n".join(f"  - {k}" for k in orphans)
        )


@pytest.mark.parametrize("method", _path_method_names())
def test_registry_entry_fields_valid(method):
    """每条注册表条目的四个属性值必须在允许集合内。"""
    entry = REGISTRY.get(method)
    assert entry is not None, f"REGISTRY 缺少 {method} 条目"
    assert isinstance(entry, PathMeta), f"REGISTRY[{method!r}] 不是 PathMeta 实例"
    assert entry.durability in _VALID_DURABILITY, (
        f"REGISTRY[{method!r}].durability={entry.durability!r} 不合法"
    )
    assert entry.domain in _VALID_DOMAIN, (
        f"REGISTRY[{method!r}].domain={entry.domain!r} 不合法"
    )
    assert entry.scope in _VALID_SCOPE, (
        f"REGISTRY[{method!r}].scope={entry.scope!r} 不合法"
    )
    assert entry.git_policy in _VALID_GIT_POLICY, (
        f"REGISTRY[{method!r}].git_policy={entry.git_policy!r} 不合法"
    )

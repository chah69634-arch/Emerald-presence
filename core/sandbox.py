"""
测试沙盒隔离 — DataPaths 单例（胶水层）
实现层：core/data_paths.py；迁移辅助：core/migration.py
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

from core.data_paths import (  # noqa: E402
    DataPaths, safe_user_id,
    _LAYOUT_CHARACTER_INNER, _LAYOUT_REALITY, _LAYOUT_DREAM,
    _TRANSITION_CHARACTER_INNER,
)
from core.migration import (  # noqa: E402
    for_read, get_fallback_stats, reset_fallback_hit_count,
    _FALLBACK_RECENT_MAX,
)

_instance: DataPaths | None = None


def get_paths() -> DataPaths:
    global _instance
    if _instance is None:
        _instance = DataPaths()
    return _instance


def init_paths(mode: str | None = None, test_session_id: str | None = None) -> DataPaths:
    """项目启动时调用一次（run_test.py 用），之后所有模块调用 get_paths()。"""
    global _instance
    _instance = DataPaths(mode=mode, test_session_id=test_session_id)
    if _instance.mode == "test":
        _write_active_prefix(str(_instance._base).replace("\\", "/"))
        logger.info(
            f"[sandbox] TEST 模式已激活 session={_instance.test_session_id} "
            f"数据根目录={_instance._base}"
        )
    return _instance


def _write_active_prefix(prefix: str):
    """把沙盒前缀写入 config.yaml 的 data_prefix 字段，供 Emerald-desktop 读取。"""
    try:
        lines = _CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("data_prefix:"):
                lines[i] = f'data_prefix: "{prefix}"\n'
                updated = True
                break
        if not updated:
            lines.append(f'data_prefix: "{prefix}"\n')
        _CONFIG_PATH.write_text("".join(lines), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[sandbox] 写入 config.yaml data_prefix 失败: {e}")

"""
run_test.py — 以 test 模式启动 qq-st-bot。
数据全部写入 data/test_sandbox/{session_id}/，不污染 production 数据。
代替 main.py 使用；结束后询问是否清理沙盒目录。
"""

import asyncio
import os
import sys
from pathlib import Path

# ── 1. 切换到 qq-st-bot 目录，与 main.py 保持一致 ────────────────────────────
os.chdir(Path(__file__).parent)

# ── 2. 初始化沙盒（必须在所有项目模块导入之前）────────────────────────────────
from core.sandbox import init_paths

_paths = init_paths(mode="test")

print("=" * 60)
print(f"[TEST] session_id  : {_paths.test_session_id}")
print(f"[TEST] 数据根目录   : {_paths._base.resolve()}")
print(f"[TEST] config.yaml 已写入 data_prefix 字段（供 Emerald-desktop （该前端已废弃，现在Emerald-client）同步）")
print("=" * 60)
print()

# ── 3. 导入并运行主程序 ────────────────────────────────────────────────────────
import main as _main_module

if __name__ == "__main__":
    try:
        asyncio.run(_main_module.main())
    except KeyboardInterrupt:
        print()
        print("[TEST] 服务已停止")
    finally:
        print()
        answer = input(f"是否清理沙盒数据 {_paths._base}？(y/n) ").strip().lower()
        if answer == "y":
            _paths.cleanup()
            print("[TEST] 沙盒已清理")

            # 同时从 config.yaml 移除 data_prefix 字段
            from core.sandbox import _CONFIG_PATH
            lines = _CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
            lines = [l for l in lines if not l.startswith("data_prefix:")]
            _CONFIG_PATH.write_text("".join(lines), encoding="utf-8")
            print("[TEST] config.yaml data_prefix 已重置")
        else:
            print(f"[TEST] 沙盒保留在 {_paths._base.resolve()}")

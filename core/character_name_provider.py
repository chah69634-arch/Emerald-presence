"""
角色显示名权威来源。

规则：
- prompt/tool/scheduler 层一律调用 get_active_char_name()，不读 config。
- config.character.name 只用于选择 active_character（由 data_paths / pipeline 读取）。
- pipeline 未注册时返回受控占位符，不静默回退到任何硬编码角色名。
"""


def get_active_char_name() -> str:
    """从 pipeline registry 取当前活跃角色的 character card name。

    pipeline 未注册（测试隔离、启动前）时返回 "(角色未加载)" 而非任何私有角色名。
    调用方若需要 fail-loud，自行检查返回值是否为该占位符。
    """
    from core import pipeline_registry
    pl = pipeline_registry.get()
    if pl is not None and pl.character is not None:
        return pl.character.name
    return "(角色未加载)"

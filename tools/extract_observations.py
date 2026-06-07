"""
离线脚本：从 episodic_memory 抽取小观察，存入 observations.jsonl。
手动运行：python tools/extract_observations.py
不进入主流程，按需跑。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.sandbox import get_paths
from core import llm_client
from core.config_loader import get_config, _char_name

_CHAR = _char_name()
EXTRACT_PROMPT = f"""以下是一些情景记忆片段（emotion_texture字段）。
请从中提取{_CHAR}对用户的具体小观察——不是宏观印象，是非常细节的行为模式。
格式：每行一条，20字以内，{_CHAR}视角，像她私下记在心里的事。
示例：
- 写代码写到一半会停下来喝水
- 周三晚上比平时容易烦躁
- 说"随便"的时候其实有想法

只输出观察列表，每行一条，不要编号，不要解释。

情景记忆：
{{memories}}"""

async def main():
    uid = get_config().get("default_user_id", "")
    if not uid:
        # v1: 从 memory_char_root 找第一个有 profile.json 的用户目录
        char_root = get_paths().memory_char_root()
        if char_root.exists():
            for d in sorted(char_root.iterdir()):
                if d.is_dir() and (d / "profile.json").exists():
                    uid = d.name
                    break
        # legacy fallback
        if not uid:
            profiles_dir = get_paths().profiles()
            if profiles_dir.exists():
                files = list(profiles_dir.glob("*.json"))
                if files:
                    uid = files[0].stem
    if not uid:
        print("找不到用户ID，请在config.yaml里设置default_user_id")
        return

    from core.sandbox import safe_user_id
    safe_uid = safe_user_id(uid)
    mem_file = get_paths().user_memory_root(safe_uid) / "episodic.json"
    if not mem_file.exists():
        print(f"找不到情景记忆文件: {mem_file}")
        return

    memories = json.loads(mem_file.read_text(encoding="utf-8"))
    textures = [m.get("emotion_texture", "") for m in memories if m.get("emotion_texture")]
    if not textures:
        print("没有找到 emotion_texture 数据")
        return

    print(f"找到 {len(textures)} 条情景记忆，开始抽取观察...")

    # 分批处理，每批20条
    all_observations = []
    for i in range(0, len(textures), 20):
        batch = textures[i:i+20]
        prompt = EXTRACT_PROMPT.replace("{memories}", "\n".join(f"- {t}" for t in batch))
        try:
            result = await llm_client.chat([{"role": "user", "content": prompt}])
            lines = [l.strip().lstrip("-").strip() for l in result.strip().splitlines() if l.strip()]
            all_observations.extend(lines)
            print(f"批次 {i//20+1}：抽取到 {len(lines)} 条")
        except Exception as e:
            print(f"批次 {i//20+1} 失败: {e}")

    if not all_observations:
        print("没有抽取到任何观察")
        return

    # 去重
    seen = set()
    unique = []
    for obs in all_observations:
        if obs not in seen and len(obs) > 3:
            seen.add(obs)
            unique.append(obs)

    # 写入 observations.jsonl
    from datetime import datetime as _dt
    _ts = _dt.now().isoformat(timespec="seconds")
    # Legacy standalone tool; no routing context — writes to yexuan's observations file.
    obs_path = get_paths().observations(char_id="yexuan")
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(obs_path, "w", encoding="utf-8") as f:
        for obs in unique:
            f.write(json.dumps({"text": obs, "weight": 1, "last_used_at": 0, "inserted_at": _ts}, ensure_ascii=False) + "\n")

    print(f"完成，共写入 {len(unique)} 条观察到 {obs_path}")

if __name__ == "__main__":
    asyncio.run(main())

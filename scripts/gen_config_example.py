"""scripts/gen_config_example.py — 从真实 config.yaml 生成脱敏的完整配置示例。

用法: python scripts/gen_config_example.py
输出: config.yaml.example.generated（人工审查无泄漏后，重命名覆盖 config.yaml.example）

脱敏规则:
- api_key / secret / password / token(独立词) / owner_id / target_qq → CHANGE_ME 或假号
- birthday / anniversaries / location / nickname → 占位
- Windows 绝对路径 → 留空
其余键值原样保留，保证示例与真实配置键集合 100% 对齐。
"""
import yaml, re, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENSITIVE_KEY = re.compile(r"(api_key|secret|password|owner_id|target_qq|qq_number|(?<![a-z_])token(?!s))", re.I)
PATH_KEY = re.compile(r"(path|dir|root)$", re.I)
PERSONAL_KEY = re.compile(r"(birthday|anniversar|location|nickname|real_name)", re.I)


def redact(obj, keypath=""):
    if isinstance(obj, dict):
        return {k: redact(v, f"{keypath}.{k}" if keypath else str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        if PERSONAL_KEY.search(keypath):
            return []
        return [redact(v, keypath) for v in obj]
    key = keypath.rsplit(".", 1)[-1]
    if SENSITIVE_KEY.search(key):
        return "10001" if ("owner" in key.lower() or "qq" in key.lower()) else "CHANGE_ME"
    if PERSONAL_KEY.search(keypath):
        if isinstance(obj, int):
            return 1
        if isinstance(obj, str):
            return ""
        return obj
    if isinstance(obj, str) and (
        PATH_KEY.search(key) and any(c in obj for c in (":\\", ":/"))
        or re.match(r"^[A-Za-z]:[\\/]", obj)
    ):
        return ""
    return obj


def main():
    real = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
    red = redact(real)
    header = (
        "# config.yaml.example — 由 scripts/gen_config_example.py 从真实配置脱敏生成\n"
        "# 复制为 config.yaml 并填入: llm.api_key / vision.api_key / admin.secret_key / scheduler.owner_id\n"
        "# 路径类字段(留空的)按本机环境填写。个人信息字段(birthday/anniversaries等)按需填写。\n\n"
    )
    out = header + yaml.safe_dump(red, allow_unicode=True, sort_keys=False, default_flow_style=False)
    dst = os.path.join(ROOT, "config.yaml.example.generated")
    fd, tmp = tempfile.mkstemp(dir=ROOT, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dst)
    leaks = [p for p in [r"sk-[A-Za-z0-9]{10,}", r"@gmail", r"[A-Za-z]:\\\\"] if re.search(p, out)]
    print(f"written: {dst}")
    print("leak self-check:", leaks or "clean")
    print("NOTE: 人工审查后再重命名为 config.yaml.example")


if __name__ == "__main__":
    main()

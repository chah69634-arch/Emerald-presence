import re

# 硬名单：整句仅由这些构成时视为 backchannel。保守起步，宁漏勿误伤。
_BACKCHANNEL = {
    "嗯", "嗯嗯", "嗯嗯嗯", "嗯哼", "唔", "哦", "噢", "哦哦", "噢噢",
    "好", "好的", "好吧", "好滴", "行", "成", "ok", "okk", "okok",
    "在", "在的", "哈", "哈哈", "哈哈哈", "嘿", "诶", "唉",
    "咪", "喵", "知道了", "晓得了", "收到", "懂了", "嗯呐",
}
# 允许单字符重复成 backchannel 的字符集（嗯嗯嗯/哈哈哈/喵喵喵）
_REPEAT_CHARS = set("嗯哦噢唔哈喵咪诶唉嘿啊")


def is_low_information(text: str) -> bool:
    """整句去标点/空白/emoji 后，若全是 backchannel 或单字符重复，则视为低信息轮。"""
    if not text:
        return True
    s = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    if not s:
        return True
    if s in _BACKCHANNEL:
        return True
    if len(set(s)) == 1 and s[0] in _REPEAT_CHARS:
        return True
    return False

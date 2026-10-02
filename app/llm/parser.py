"""解析模型输出：提取 [Video Prompt] 代码框里的英文提示词 + <seconds>N</seconds> 总时长。"""

import re

_SECONDS_RE = re.compile(r"<seconds>\s*(\d{1,2})\s*</seconds>", re.I)


def extract_video_prompt(text: str) -> str | None:
    if not text:
        return None
    # 首选：[Video Prompt] 标题后的第一个代码框
    m = re.search(r"\[Video Prompt\].*?```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if m and m.group(1).strip():
        return _strip_seconds(m.group(1).strip())
    # 次选：全文第一个代码框
    m = re.search(r"```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if m and m.group(1).strip():
        return _strip_seconds(m.group(1).strip())
    # 兜底：标题后面的全部内容（模型没按格式时也能捞到）
    m = re.search(r"\[Video Prompt\]\s*(.+)", text, re.S)
    if m and len(m.group(1).strip()) > 100:
        return _strip_seconds(m.group(1).strip())
    return None


def _strip_seconds(prompt: str) -> str:
    """时长标签只给程序用，不能混进发给视频模型的提示词。"""
    return _SECONDS_RE.sub("", prompt).strip()


def extract_duration(text: str, lo: int = 1, hi: int = 60) -> int | None:
    """从模型输出里取 <seconds>N</seconds>，并钳制到 [lo, hi]。

    返回 None 表示模型没给标签（旧格式输出），调用方用配置回退值。
    """
    m = _SECONDS_RE.search(text or "")
    if not m:
        return None
    n = int(m.group(1))
    return max(lo, min(hi, n))


def extract_hook(video_prompt: str) -> str:
    """开头台词（用于后续避开重复 Hook）。"""
    for line in video_prompt.splitlines():
        low = line.lower()
        if "shot 1" in low or "0-2s" in low or "0–2s" in low:
            return line.strip()[:150]
    return video_prompt.strip()[:150]

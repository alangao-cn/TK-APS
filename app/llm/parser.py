"""解析模型输出：提取 [Video Prompt] 代码框里的英文提示词。"""

import re


def extract_video_prompt(text: str) -> str | None:
    if not text:
        return None
    # 首选：[Video Prompt] 标题后的第一个代码框
    m = re.search(r"\[Video Prompt\].*?```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # 次选：全文第一个代码框
    m = re.search(r"```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # 兜底：标题后面的全部内容（模型没按格式时也能捞到）
    m = re.search(r"\[Video Prompt\]\s*(.+)", text, re.S)
    if m and len(m.group(1).strip()) > 100:
        return m.group(1).strip()
    return None


def extract_hook(video_prompt: str) -> str:
    """开头台词（用于后续避开重复 Hook）。"""
    for line in video_prompt.splitlines():
        low = line.lower()
        if "shot 1" in low or "0-2s" in low or "0–2s" in low:
            return line.strip()[:150]
    return video_prompt.strip()[:150]

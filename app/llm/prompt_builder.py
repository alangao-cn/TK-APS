"""拼接系统指令：prompts/director_base.md + prompts/market_{region}.md，替换变量。"""

import hashlib
import re
from pathlib import Path


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def load_instructions(cfg, region: str, recent_hooks: list[str] | None = None) -> tuple[str, str]:
    """返回 (系统指令全文, 内容哈希)。变量取自 config.yaml 的 video 段。"""
    base_path = Path(cfg.llm.prompts.base)
    market_path = Path(cfg.llm.prompts.market_dir) / f"market_{region}.md"
    if not base_path.exists():
        raise FileNotFoundError(f"prompt 模板不存在：{base_path}")
    parts = [_strip_comments(base_path.read_text(encoding="utf-8"))]
    if market_path.exists():
        parts.append(_strip_comments(market_path.read_text(encoding="utf-8")))
    text = "\n\n".join(parts)

    replacements = {
        "{{seconds}}": str(cfg.video.duration),
        "{{shots}}": str(cfg.video.shots),
        "{{ratio}}": cfg.video.ratio,
        "{{product_ref}}": cfg.video.product_ref,
    }
    for key, value in replacements.items():
        text = text.replace(key, value)

    if recent_hooks:
        text += ("\n\n【最近已用过的开头（必须避开这些句子和相似句式）】\n"
                 + "\n".join(f"- {h}" for h in recent_hooks))

    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

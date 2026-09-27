"""ZenMux（OpenAI 兼容 Responses API）调用封装。"""

import asyncio
import base64
import os
from io import BytesIO
from pathlib import Path

from openai import AsyncOpenAI


def compress_image_to_data_url(path: str | Path, max_side: int = 1024) -> str | None:
    """图片压到长边 1024 的 JPEG data URL，控制 token 消耗。失败返回 None（只传文字）。"""
    try:
        from PIL import Image

        img = Image.open(path)
        img.thumbnail((max_side, max_side))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


async def generate(cfg, instructions: str, product_brief: str,
                   image_paths: list[str]) -> dict:
    """调一次 Responses API，返回 {output_text, usage}。"""
    client = AsyncOpenAI(
        base_url=cfg.llm.base_url,
        api_key=os.environ.get("ZENMUX_API_KEY", ""),
        timeout=cfg.llm.timeout_seconds,
    )

    content: list[dict] = [{"type": "input_text", "text": product_brief}]
    if getattr(cfg.llm, "send_image", True):
        for path in image_paths[: int(getattr(cfg.llm, "max_images", 1))]:
            url = compress_image_to_data_url(path)
            if url:
                content.append({"type": "input_image", "image_url": url})

    kwargs: dict = {
        "model": cfg.llm.model,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": cfg.llm.max_output_tokens,
    }
    effort = getattr(cfg.llm, "reasoning_effort", None)
    if effort:
        kwargs["reasoning"] = {"effort": effort}

    resp = await client.responses.create(**kwargs)
    usage = getattr(resp, "usage", None)
    return {
        "output_text": resp.output_text or "",
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    }

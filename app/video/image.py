"""图片转 base64（视频参考图用）：控制体积的同时尽量保留商品细节。"""

import base64
from io import BytesIO
from pathlib import Path


def image_to_base64_jpeg(path: str | Path, max_side: int = 1568, quality: int = 90) -> tuple[str, str]:
    """返回 (base64, mimeType)。webp/png 统一转 jpeg，视频模型兼容性最好。"""
    from PIL import Image

    img = Image.open(path)
    img.thumbnail((max_side, max_side))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"

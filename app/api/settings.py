"""配置：查看 / 保存（YAML 校验 + 热重载）。"""

import os

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import load_config

router = APIRouter()


@router.get("/settings")
async def get_settings(request: Request):
    cfg = request.app.state.cfg
    config_text = (cfg.root / "config.yaml").read_text(encoding="utf-8")
    env_items = [
        ("ZENMUX_API_KEY", "已配置" if os.environ.get("ZENMUX_API_KEY") else "未配置"),
        ("FASTMOSS_PHONE", "已配置" if os.environ.get("FASTMOSS_PHONE") else "未配置"),
        ("WEB_USERNAME", os.environ.get("WEB_USERNAME", "admin")),
        ("DATABASE_URL", os.environ.get("DATABASE_URL") or "默认 SQLite 文件"),
    ]
    return {"config_text": config_text, "env_items": env_items,
            "llm_model": cfg.llm.model, "video_model": cfg.video.model}


class ConfigBody(BaseModel):
    config_text: str


@router.put("/settings")
async def save_settings(request: Request, body: ConfigBody):
    try:
        parsed = yaml.safe_load(body.config_text)
        if not isinstance(parsed, dict):
            raise ValueError("YAML 顶层应该是键值结构")
        (request.app.state.cfg.root / "config.yaml").write_text(body.config_text, encoding="utf-8")
        request.app.state.cfg = load_config()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"配置未保存：{e}"}, status_code=400)


@router.post("/settings/reload")
async def reload_settings(request: Request):
    try:
        request.app.state.cfg = load_config()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"重载失败：{e}"}, status_code=500)

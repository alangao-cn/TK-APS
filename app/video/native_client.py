"""方式 B：ZenMux 原生接口（Seedance 原生参数最全，如 watermark）。
POST /api/v1/videos 提交，GET /api/v1/videos/{id} 轮询。"""

import os

import httpx

from . import errors


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('ZENMUX_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def build_payload(cfg, prompt: str, image_b64: str, image_mime: str) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    role = cfg.video.image_role
    if role in ("reference_image", "first_frame", "last_frame") and image_b64:
        content.append({
            "type": "image_url",
            "role": role,
            "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
        })
    payload: dict = {
        "model": cfg.video.model,
        "content": content,
        "duration": int(cfg.video.duration),
        "ratio": cfg.video.ratio,
        "resolution": cfg.video.resolution,
        "generate_audio": bool(cfg.video.generate_audio),
    }
    # Seedance 系的习惯字段：不设置就不传，对齐官方最小请求，换模型不踩字段坑
    if int(cfg.video.seed) >= 0:
        payload["seed"] = int(cfg.video.seed)        # -1 = 随机
    if cfg.video.watermark:
        payload["watermark"] = True                  # 默认 false，不传等效
    if cfg.video.callback_url:
        payload["callback_url"] = cfg.video.callback_url
    return payload


async def submit(cfg, http: httpx.AsyncClient, prompt: str,
                 image_b64: str, image_mime: str) -> str:
    resp = await http.post(f"{cfg.video.native_base_url}/videos",
                           json=build_payload(cfg, prompt, image_b64, image_mime),
                           headers=_headers())
    if resp.status_code not in (200, 201):
        if errors.is_model_not_supported(resp.status_code, resp.text):
            raise errors.ModelNotSupported(
                f"native 接口不支持模型 {cfg.video.model}: {resp.text[:200]}")
        raise RuntimeError(f"提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("id"):
        raise RuntimeError(f"提交响应异常: {str(data)[:300]}")
    return data["id"]


async def poll(cfg, http: httpx.AsyncClient, job_id: str) -> dict:
    resp = await http.get(f"{cfg.video.native_base_url}/videos/{job_id}", headers=_headers())
    if resp.status_code == 404:
        return {"_status": "expired"}
    if resp.status_code != 200:
        raise RuntimeError(f"轮询失败 HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def extract_result(job: dict) -> dict:
    """返回统一结果：{kind: url|base64|filtered|error|pending, ...}。"""
    status = job.get("status")
    if status in ("queued", "running"):
        return {"kind": "pending"}
    if status == "failed":
        err = job.get("error") or {}
        return {"kind": "error", "message": f"{err.get('code')}: {err.get('message')}"}
    if status == "succeeded":
        content = job.get("content") or {}
        if content.get("video_url"):
            return {"kind": "url", "url": content["video_url"]}
        return {"kind": "error", "message": "succeeded 但没有 video_url: " + str(job)[:300]}
    return {"kind": "error", "message": f"未知 status: {status}"}

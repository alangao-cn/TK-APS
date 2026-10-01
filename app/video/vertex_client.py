"""方式 A：Vertex AI 兼容接口（默认）。
POST /v1/publishers/{厂商}/models/{模型}:predictLongRunning 提交，
     /v1/publishers/{厂商}/models/{模型}:fetchPredictOperation 轮询。
换模型只改 config.yaml 的 video.model（如 google/veo-3.1-generate-001）。"""

import httpx

from . import errors


def _url(cfg, action: str) -> str:
    provider, model = cfg.video.model.split("/", 1)
    return f"{cfg.video.vertex_base_url}/v1/publishers/{provider}/models/{model}:{action}"


def _headers() -> dict:
    import os

    return {
        "Authorization": f"Bearer {os.environ.get('ZENMUX_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def build_payload(cfg, prompt: str, image_b64: str, image_mime: str) -> dict:
    instance: dict = {"prompt": prompt}
    role = cfg.video.image_role
    if role == "reference_image" and image_b64:
        instance["referenceImages"] = [{
            "image": {"bytesBase64Encoded": image_b64, "mimeType": image_mime},
            "referenceType": "asset",
        }]
    elif role == "first_frame" and image_b64:
        instance["image"] = {"bytesBase64Encoded": image_b64, "mimeType": image_mime}

    params: dict = {
        "aspectRatio": cfg.video.ratio,
        "resolution": cfg.video.resolution,
        "durationSeconds": int(cfg.video.duration),
        "generateAudio": bool(cfg.video.generate_audio),
        "sampleCount": 1,
    }
    if cfg.video.negative_prompt:
        params["negativePrompt"] = cfg.video.negative_prompt
    if int(cfg.video.seed) >= 0:
        params["seed"] = int(cfg.video.seed)

    return {"instances": [instance], "parameters": params}


async def submit(cfg, http: httpx.AsyncClient, prompt: str,
                 image_b64: str, image_mime: str) -> str:
    """提交任务，返回 operationName。"""
    resp = await http.post(_url(cfg, "predictLongRunning"),
                           json=build_payload(cfg, prompt, image_b64, image_mime),
                           headers=_headers())
    if resp.status_code != 200:
        if errors.is_model_not_supported(resp.status_code, resp.text):
            raise errors.ModelNotSupported(
                f"vertex 接口不支持模型 {cfg.video.model}: {resp.text[:200]}")
        raise RuntimeError(f"提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "name" not in data:
        raise RuntimeError(f"提交响应异常: {str(data)[:300]}")
    return data["name"]


async def poll(cfg, http: httpx.AsyncClient, operation_name: str) -> dict:
    """查询一次进度，返回 operation dict（done=True 表示完成）。"""
    resp = await http.post(_url(cfg, "fetchPredictOperation"),
                           json={"operationName": operation_name}, headers=_headers())
    if resp.status_code != 200:
        raise RuntimeError(f"轮询失败 HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def extract_result(operation: dict) -> dict:
    """从完成的 operation 里取结果：{kind: url|base64|filtered|error, ...}。"""
    if "error" in operation and operation.get("error"):
        return {"kind": "error", "message": str(operation["error"])[:500]}
    response = operation.get("response") or {}
    if response.get("raiMediaFilteredCount"):
        reasons = response.get("raiMediaFilteredReasons") or []
        return {"kind": "filtered", "message": "内容审核拦截: " + "; ".join(map(str, reasons))[:400]}
    videos = response.get("videos") or []
    if not videos:
        return {"kind": "error", "message": "完成但没有 videos 字段: " + str(response)[:300]}
    v = videos[0]
    if v.get("gcsUri"):
        return {"kind": "url", "url": v["gcsUri"], "mime": v.get("mimeType", "video/mp4")}
    if v.get("bytesBase64Encoded"):
        return {"kind": "base64", "b64": v["bytesBase64Encoded"], "mime": v.get("mimeType", "video/mp4")}
    return {"kind": "error", "message": "videos[0] 无下载字段: " + str(v)[:300]}

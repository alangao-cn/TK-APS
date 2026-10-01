"""第三步主流程：读第二步脚本 → 提交视频任务 → 轮询 → 下载 → 存 data/videos/{商品ID}/。

产出：video_v{N}.mp4 + video_v{N}.json（模型、参数、任务号、耗时、对应的脚本版本，全留底）。
"""

import asyncio
import base64
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

from . import errors as video_errors
from . import image as video_image
from . import native_client, vertex_client


def latest_script(cfg, product_id: str, version: int | None = None) -> Path:
    """找商品最新一版（或指定版本）的成功脚本。"""
    script_dir = cfg.root / cfg.storage.data_dir / "scripts" / product_id
    if not script_dir.exists():
        raise SystemExit(f"没有 {product_id} 的脚本，先跑 `uv run cli.py gen-scripts --product {product_id}`")
    if version:
        path = script_dir / f"script_v{version}.json"
        if not path.exists():
            raise SystemExit(f"没有 {path}")
    else:
        candidates = sorted(script_dir.glob("script_v*.json"))
        ok = [p for p in candidates
              if json.loads(p.read_text(encoding="utf-8")).get("status") == "ok"]
        if not ok:
            raise SystemExit(f"{product_id} 没有生成成功的脚本（全部解析失败？）")
        path = ok[-1]
    return path


def available_scripts(cfg) -> list[dict]:
    root = cfg.root / cfg.storage.data_dir / "scripts"
    out = []
    for d in sorted(root.iterdir()) if root.exists() else []:
        for f in sorted(d.glob("script_v*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("status") == "ok":
                out.append({"product_id": d.name, "version": rec["version"],
                            "created_at": rec.get("created_at"), "path": str(f)})
    return out


def _reference_candidates(cfg, script_record: dict) -> list[Path]:
    """参考图候选：脚本用的那张排第一，其余商品图按序号排后（审核拦截时依次降级）。"""
    imgs: list[Path] = []
    for p in script_record.get("images_used") or []:
        if Path(p).exists():
            imgs.append(Path(p))
    pid = script_record.get("product_id")
    gallery = sorted(
        (cfg.root / cfg.storage.data_dir / "images").glob(f"{pid}_*"),
        key=lambda p: int(p.stem.rsplit("_", 1)[-1]) if p.stem.rsplit("_", 1)[-1].isdigit() else 0,
    )
    for p in gallery:
        if p not in imgs:
            imgs.append(p)
    return imgs


def _next_version(video_dir: Path) -> int:
    versions = [int(f.stem.split("_v")[-1]) for f in video_dir.glob("video_v*.json")]
    return max(versions, default=0) + 1


async def _download_video(http: httpx.AsyncClient, url: str, dest: Path) -> None:
    resp = await http.get(url)
    if resp.status_code in (401, 403):
        resp = await http.get(url, headers={"Authorization": _auth_header()})
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def _auth_header() -> str:
    import os

    return f"Bearer {os.environ.get('ZENMUX_API_KEY', '')}"


async def generate_for_script(cfg, product_id: str, script_version: int | None = None,
                              image_index: int | None = None) -> Path | None:
    script_path = latest_script(cfg, product_id, script_version)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    prompt = script["video_prompt"]

    candidates = _reference_candidates(cfg, script)
    if image_index is not None:
        if not candidates or image_index >= len(candidates):
            raise SystemExit(f"没有第 {image_index} 张图（共 {len(candidates)} 张）")
        candidates = [candidates[image_index]]
    if not candidates and cfg.video.image_role != "none":
        print("[视频] 找不到商品图，将不传参考图（只靠文字描述）")

    video_dir = cfg.root / cfg.storage.data_dir / "videos" / product_id
    video_dir.mkdir(parents=True, exist_ok=True)
    version = _next_version(video_dir)
    # 两条通道（vertex 兼容 / native）各自只支持一部分模型：配置的通道不认模型时自动换另一条
    client_mod = vertex_client if cfg.video.api == "vertex" else native_client
    api_name = cfg.video.api

    record = {
        "product_id": product_id,
        "script_version": script["version"],
        "script_file": str(script_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "api": cfg.video.api,
        "model": cfg.video.model,
        "params": {"duration": cfg.video.duration, "ratio": cfg.video.ratio,
                   "resolution": cfg.video.resolution, "generate_audio": cfg.video.generate_audio,
                   "image_role": cfg.video.image_role},
        "version": version,
        "attempts": [],
    }

    result: dict = {"kind": "error", "message": "没有可用的参考图"}
    started = time.monotonic()
    max_attempts = max(1, int(getattr(cfg.video, "max_image_attempts", 3)))

    async with httpx.AsyncClient(timeout=120) as http:
        for attempt in range(min(max_attempts, max(1, len(candidates))) if candidates else 1):
            image_b64, image_mime, img_path = "", "", None
            if candidates and cfg.video.image_role != "none":
                img_path = candidates[attempt]
                image_b64, image_mime = video_image.image_to_base64_jpeg(img_path)
                print(f"[视频] 参考图：{img_path.name}（{len(image_b64) // 1024} KB base64，"
                      f"第 {attempt + 1} 次尝试）")

            print(f"[视频] {product_id} 提交任务（{api_name} / {cfg.video.model}）…")
            try:
                job_id = await client_mod.submit(cfg, http, prompt, image_b64, image_mime)
            except video_errors.ModelNotSupported as e:
                other = native_client if client_mod is vertex_client else vertex_client
                other_name = "native" if other is native_client else "vertex"
                print(f"[视频] {api_name} 接口不认这个模型（{str(e)[:160]}），"
                      f"自动切换 {other_name} 接口重试…")
                client_mod, api_name = other, other_name
                record["api"] = api_name
                try:
                    job_id = await client_mod.submit(cfg, http, prompt, image_b64, image_mime)
                except video_errors.ModelNotSupported as e2:
                    raise RuntimeError(
                        f"模型 {cfg.video.model} 在 vertex 和 native 两条接口都不支持"
                        f"（{str(e2)[:160]}）。模型名以 GET /api/v1/models 返回为准") from e2
            print(f"[视频] 任务号 {job_id}（{api_name}），每 {cfg.video.poll_interval_seconds}s 轮询一次…")

            poll_started = time.monotonic()
            while True:
                await asyncio.sleep(int(cfg.video.poll_interval_seconds))
                elapsed = int(time.monotonic() - poll_started)
                if client_mod is vertex_client:
                    operation = await client_mod.poll(cfg, http, job_id)
                    if operation.get("done"):
                        result = client_mod.extract_result(operation)
                        break
                else:
                    job = await client_mod.poll(cfg, http, job_id)
                    result = client_mod.extract_result(job)
                    if result["kind"] != "pending":
                        break
                if elapsed > int(cfg.video.timeout_seconds):
                    result = {"kind": "error", "message": f"超时（>{cfg.video.timeout_seconds}s）"}
                    break
                print(f"[视频] …进行中（{elapsed}s）")

            record["job_id"] = job_id
            record["attempts"].append({
                "image": str(img_path) if img_path else None,
                "job_id": job_id,
                "result": result["kind"],
                "message": result.get("message", "")[:200] or result.get("url", "")[:200],
            })

            # 服装类商品图常带真人模特，会被 Seedance 审核拦截 → 自动换下一张图重试
            person_blocked = (result["kind"] == "filtered"
                              and "person" in result.get("message", "").lower())
            more_images = candidates and attempt + 1 < min(max_attempts, len(candidates))
            if person_blocked and more_images:
                print("[视频] 该图被审核拦截（疑似含真人），自动换下一张商品图重试…")
                continue
            break

        record["elapsed_seconds"] = int(time.monotonic() - started)
        record["finished_at"] = datetime.now().isoformat(timespec="seconds")

        if result["kind"] == "url":
            dest = video_dir / f"video_v{version}.mp4"
            await _download_video(http, result["url"], dest)
            record["status"] = "succeeded"
            record["remote_url"] = result["url"]
            record["file"] = str(dest)
            record["file_size_mb"] = round(dest.stat().st_size / 1024 / 1024, 2)
            print(f"[视频] 完成 {dest}（{record['file_size_mb']} MB，耗时 {record['elapsed_seconds']}s）")
        elif result["kind"] == "base64":
            dest = video_dir / f"video_v{version}.mp4"
            dest.write_bytes(base64.b64decode(result["b64"]))
            record["status"] = "succeeded"
            record["file"] = str(dest)
            record["file_size_mb"] = round(dest.stat().st_size / 1024 / 1024, 2)
            print(f"[视频] 完成（base64 → {dest}，{record['file_size_mb']} MB，耗时 {record['elapsed_seconds']}s）")
        else:
            record["status"] = result["kind"]
            record["error"] = result.get("message", "")
            print(f"[视频] 失败（{result['kind']}）：{record['error']}")

    out = video_dir / f"video_v{version}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return out if record["status"] == "succeeded" else None


async def generate_for_products(cfg, products: list[str], script_version: int | None = None,
                                image_index: int | None = None) -> list[Path]:
    if len(products) > int(cfg.video.max_videos_per_batch):
        raise SystemExit(f"一次最多 {cfg.video.max_videos_per_batch} 条（当前 {len(products)}），防止误操作产生大量费用")
    saved = []
    for i, pid in enumerate(products, 1):
        print(f"[视频] {i}/{len(products)} 商品 {pid}")
        out = await generate_for_script(cfg, pid, script_version, image_index)
        if out:
            saved.append(out)
        await asyncio.sleep(3)
    return saved

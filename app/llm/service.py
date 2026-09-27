"""第二步主流程：读选品结果 → 逐商品生成视频脚本 → 存 data/scripts/{商品ID}/。

每次生成写 script_v{N}.json（含模型、prompt 哈希、原始输出、token 用量，可回溯对比）
和 script_latest.md（可读版，方便直接复制提示词）。
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from . import client, parser, prompt_builder


def load_selection(cfg, from_path: str | None = None) -> dict:
    """读最新一次选品结果（selected.json）。"""
    path = Path(from_path) if from_path else (
        cfg.root / cfg.storage.data_dir / "selection" / "selected_latest.json"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"找不到选品结果 {path}，先跑 `uv run cli.py scrape` 或用 --from 指定 selected.json"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def pick_products(selection: dict, product_id: str | None = None,
                  all_flag: bool = False) -> list[dict]:
    products = selection.get("products") or []
    if product_id:
        matched = [p for p in products if str(p["product_id"]) == str(product_id)]
        if not matched:
            raise SystemExit(f"选品结果里没有商品 {product_id}")
        return matched
    if all_flag:
        return list(products)
    # 默认只处理人工确认过的（selected.json 的 confirmed=true），防止误消耗 token
    return list(products) if selection.get("confirmed") else []


def _recent_hooks(cfg, limit: int) -> list[str]:
    """从已有脚本里收集最近用过的开头，传给模型避免重复。"""
    hooks: list[tuple[str, str]] = []
    scripts_root = cfg.root / cfg.storage.data_dir / "scripts"
    for f in scripts_root.glob("*/script_v*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("hook"):
                hooks.append((d.get("created_at", ""), d["hook"]))
        except Exception:
            continue
    hooks.sort(reverse=True)
    return [h for _, h in hooks[:limit]]


def _next_version(product_dir: Path) -> int:
    versions = [int(f.stem.split("_v")[-1]) for f in product_dir.glob("script_v*.json")]
    return max(versions, default=0) + 1


def _write_latest_md(product: dict, record: dict, path: Path) -> None:
    lines = [
        f"# 视频脚本：{product.get('title', '')}",
        "",
        f"- 商品ID：`{product.get('product_id')}` ｜ 模型：{record['model']}"
        f" ｜ 生成时间：{record['created_at']}",
        f"- 版本：v{record['version']} ｜ prompt 哈希：{record['prompt_hash']}"
        f" ｜ tokens：入 {record['usage']['input_tokens']} / 出 {record['usage']['output_tokens']}",
        f"- 单件利润：¥{product.get('profit_cny')} ｜ 关联达人：{product.get('creators')}",
        "",
        "## [Video Prompt]",
        "",
        "```",
        record["video_prompt"],
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


async def generate_for_products(cfg, products: list[dict], region: str | None = None) -> list[Path]:
    region = region or cfg.selection.region
    hooks = _recent_hooks(cfg, int(getattr(cfg.llm, "avoid_recent_hooks", 20)))
    instructions, prompt_hash = prompt_builder.load_instructions(cfg, region, hooks)
    print(f"[脚本] 系统指令 {len(instructions)} 字符（哈希 {prompt_hash}），"
          f"近期避重 Hook {len(hooks)} 条")

    saved = []
    for i, product in enumerate(products, 1):
        pid = str(product["product_id"])
        brief = product.get("product_brief") or product.get("title", "")
        images = product.get("images_local") or []
        print(f"[脚本] {i}/{len(products)} 商品 {pid}（{product.get('title', '')[:36]}…）"
              f"｜ 传图 {min(len(images), int(getattr(cfg.llm, 'max_images', 1)))} 张 → 调用 {cfg.llm.model}")

        result = await client.generate(cfg, instructions, brief, images)
        video_prompt = parser.extract_video_prompt(result["output_text"])

        retries = 0
        while video_prompt is None and retries < int(cfg.llm.max_retries):
            retries += 1
            print(f"[脚本] 输出格式不符，重试 {retries}/{cfg.llm.max_retries}…")
            result = await client.generate(cfg, instructions, brief, images)
            video_prompt = parser.extract_video_prompt(result["output_text"])

        product_dir = cfg.root / cfg.storage.data_dir / "scripts" / pid
        product_dir.mkdir(parents=True, exist_ok=True)
        version = _next_version(product_dir)

        if video_prompt is None:
            record = {
                "product_id": pid, "created_at": datetime.now().isoformat(timespec="seconds"),
                "model": cfg.llm.model, "prompt_hash": prompt_hash, "version": version,
                "status": "parse_failed", "raw_output": result["output_text"],
                "usage": result["usage"],
            }
            out = product_dir / f"script_v{version}.json"
            out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[脚本] {pid} 无法提取 [Video Prompt]，原始输出已存 {out}")
            continue

        record = {
            "product_id": pid,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": cfg.llm.model,
            "prompt_hash": prompt_hash,
            "prompt_files": {"base": cfg.llm.prompts.base,
                             "market": f"prompts/market_{region}.md"},
            "version": version,
            "status": "ok",
            "product_brief": brief,
            "video_prompt": video_prompt,
            "hook": parser.extract_hook(video_prompt),
            "raw_output": result["output_text"],
            "usage": result["usage"],
            "images_used": images[: int(getattr(cfg.llm, "max_images", 1))],
        }
        out = product_dir / f"script_v{version}.json"
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_latest_md(product, record, product_dir / "script_latest.md")
        saved.append(out)
        print(f"[脚本] {pid} 完成 v{version} → {out}"
              f"（tokens 入 {result['usage']['input_tokens']} / 出 {result['usage']['output_tokens']}）")
        await asyncio.sleep(2)
    return saved

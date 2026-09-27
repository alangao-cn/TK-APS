"""离线导出：读取 raw 目录 → 解析 → 筛选 → CSV + 下载主图。
可选 enrich：打开浏览器逐个补抓详情页（多张商品图等）。
可反复重跑，不需要重新爬。"""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import detail, filters, handoff, parser

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Referer": "https://www.fastmoss.com/",
}


def _latest_raw_dir(cfg) -> Path:
    raw_root = cfg.root / cfg.storage.data_dir / "raw"
    dirs = sorted(d for d in raw_root.iterdir() if d.is_dir() and (d / "period_week.json").exists())
    if not dirs:
        raise FileNotFoundError(f"{raw_root} 下没有采集数据，先跑 `uv run cli.py scrape`")
    return dirs[-1]


def _download_images(products: list[dict], cfg) -> None:
    """下载每个商品的全部图片（详情页补抓的多图，没补抓过就用榜单主图）。"""
    img_dir = cfg.root / cfg.storage.data_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for p in products:
            pid = str(p.get("product_id") or "")
            urls = p.get("image_urls") or ([p["image"]] if p.get("image") else [])
            local_list = []
            for idx, url in enumerate(urls):
                if not url:
                    continue
                suffix = os.path.splitext(urlparse(url).path)[1] or ".jpg"
                path = img_dir / f"{pid}_{idx}{suffix}"
                if not path.exists():
                    try:
                        resp = client.get(url if str(url).startswith("http") else f"https:{url}")
                        resp.raise_for_status()
                        path.write_bytes(resp.content)
                        ok += 1
                    except Exception as e:
                        print(f"    [warn] 图片下载失败 {pid}_{idx}: {e}")
                        fail += 1
                        continue
                local_list.append(str(path))
            p["images_local"] = local_list
            if local_list:
                p["image_local"] = local_list[0]
    print(f"[图片] 下载成功 {ok}，失败 {fail}，目录 {img_dir}")


def export(cfg, raw_dir: Path | None = None, download_images: bool = True,
           enrich: bool = False) -> Path:
    raw_dir = raw_dir or _latest_raw_dir(cfg)
    all_items: list[dict] = []
    seen: set = set()
    # 只解析榜单原始数据；selected/products/detail 是本工具自己的产物，不能再喂回来
    files = sorted(
        f for f in raw_dir.glob("*.json")
        if f.name not in ("radio_values.json", "parse_report.json", "selected.json")
        and not f.name.startswith(("products_", "detail_"))
    )
    for f in files:
        items = parser.parse_raw_file(f)
        for it in items:
            pid = str(it.get("product_id") or it.get("goods_id") or it.get("id") or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            all_items.append(it)

    if not all_items:
        raise RuntimeError(f"raw 目录里没解析到商品，看下 {raw_dir} 下的 json 结构，改 parser.py 的 CANDIDATES")

    parsed = [parser.parse_item(it) for it in all_items]
    report = parser.parse_report(parsed, all_items)
    (raw_dir / "parse_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["unmapped"]:
        print(f"[解析] 以下字段没映射到（详见 parse_report.json，需补 CANDIDATES）: "
              f"{list(report['unmapped'])}")

    # 第一步产出统一放 data/selection/<时间戳>/，raw 目录只留接口原始数据
    sel_dir = cfg.root / cfg.storage.data_dir / "selection" / raw_dir.name
    sel_dir.mkdir(parents=True, exist_ok=True)

    filters.annotate_profit(parsed, cfg)
    all_rows = filters.to_rows(parsed, cfg)
    filters.write_csv(sel_dir / "products_all.csv", all_rows)
    print(f"[导出] 全部商品 {len(all_rows)} 条 → {sel_dir / 'products_all.csv'}")

    kept = filters.apply_filters(parsed, cfg)
    if enrich and kept:
        print(f"[详情] 开始补抓 {len(kept)} 个入选商品的详情页（多图等）…")
        ok = asyncio.run(detail.enrich(kept, cfg, raw_dir))
        print(f"[详情] 补抓完成 {ok}/{len(kept)}")
    kept = filters.apply_stock_filter(kept, cfg)
    rows = filters.to_rows(kept, cfg)
    filters.write_csv(sel_dir / "products_selected.csv", rows)
    print(f"[导出] 通过筛选 {len(rows)} 条 → {sel_dir / 'products_selected.csv'}")
    filters.print_summary(rows)

    if download_images and kept:
        _download_images(kept, cfg)
    json_path, md_path = handoff.write_handoff(kept, cfg, raw_dir, sel_dir)
    if kept:
        print(f"[交付] selected.json（{len(kept)} 条，给下一步 GPT 用）→ {json_path}")
        print(f"[交付] selected.md（人工确认用）→ {md_path}")
        print("[交付] 人工确认后把 selected.json 的 confirmed 改为 true，第二步才会使用")
    else:
        print(f"[交付] 本次通过筛选 0 条，selected.json 已重置为空 → {json_path}")
    return raw_dir

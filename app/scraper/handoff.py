"""第一步交付物：
- selected.json  给第二步（GPT 生成脚本）直接读的程序格式
- selected.md    人工确认用的可读版（含图片预览）
confirmed 字段默认 false，人工确认后才进入下一步。"""

import json
import os
from datetime import datetime
from pathlib import Path


def _entry(p: dict, cfg) -> dict:
    pid = str(p.get("product_id") or "")
    price = f"R$ {p.get('price_min')}"
    if p.get("price_max") and p["price_max"] != p["price_min"]:
        price += f" - {p['price_max']}"
    brief = (
        f"Product title: {p.get('title', '')}\n"
        f"Category: {p.get('category', '')}\n"
        f"Price: {price}\n"
        f"Commission rate: {p.get('commission_rate', '')}\n"
        f"Estimated profit per order: CNY {p.get('profit_cny')}\n"
        f"Recent weekly sales: {p.get('sales')} units\n"
        f"Target market: Brazil (TikTok Shop BR)\n"
        f"Reference image: attached (the product photo)"
    )
    image_urls = p.get("image_urls") or ([p["image"]] if p.get("image") else [])
    return {
        "product_id": pid,
        "title": p.get("title") or "",
        "description": p.get("description") or "",  # FastMoss 榜单/详情接口均无描述字段，标题即卖点描述
        "category": p.get("category") or "",
        "currency": p.get("currency") or "BRL",
        "price_min": p.get("price_min"),
        "price_max": p.get("price_max"),
        "commission_rate": p.get("commission_rate"),
        "creators": p.get("creators"),
        "creators_total": p.get("creators_total"),
        "sales_week": p.get("sales"),
        "revenue_week": p.get("revenue"),
        "profit_cny": p.get("profit_cny"),
        "shop": p.get("shop") or "",
        "rating": p.get("rating"),
        "stock": p.get("stock"),
        "review_count": p.get("review_count"),
        "category_rank": p.get("category_rank"),
        "image_url": image_urls[0] if image_urls else "",
        "image_urls": image_urls,           # 全部商品图（详情页 cover_list）
        "images_local": p.get("images_local") or [],  # 本地文件路径，给 GPT 传图用
        "fastmoss_url": cfg.selection.detail_url_template.format(product_id=pid),
        "tiktok_url": p.get("detail_url") or "",
        "product_brief": brief,
    }


def write_handoff(kept: list[dict], cfg, raw_dir: Path) -> tuple[Path, Path]:
    entries = [_entry(p, cfg) for p in kept]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_raw_dir": str(raw_dir),
        "filters": {
            "region": cfg.selection.region,
            "period": "weekly",
            "categories": list(cfg.selection.categories),
            "creators": [cfg.selection.creators_min, cfg.selection.creators_max],
            "min_profit_cny": cfg.selection.min_profit_cny,
        },
        "confirmed": False,  # 人工确认后才置 true，第二步只读 confirmed=true 的数据
        "products": entries,
    }
    json_path = raw_dir / "selected.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 选品结果（{payload['generated_at']}）",
        "",
        f"共 **{len(entries)}** 条通过筛选（达人数 "
        f"{cfg.selection.creators_min}-{cfg.selection.creators_max}，单件利润 ≥ "
        f"{cfg.selection.min_profit_cny} 元）。确认无误后把 selected.json 里的 confirmed 改为 true。",
        "",
    ]
    for i, e in enumerate(entries, 1):
        rel_imgs = [os.path.relpath(img, raw_dir)
                    for img in (e.get("images_local") or [])]
        price = f"R$ {e['price_min']}"
        if e["price_max"] and e["price_max"] != e["price_min"]:
            price += f" - {e['price_max']}"
        img_lines = [f"![主图{i + 1}]({rel})" for i, rel in enumerate(rel_imgs)]
        lines += [
            f"## {i}. {e['title']}",
            "",
            " ".join(img_lines) if img_lines else "（无图）",
            "",
            f"- 商品ID：`{e['product_id']}` ｜ 类目：{e['category']} ｜ 店铺：{e['shop']}",
            f"- 价格：{price} ｜ 佣金：{e['commission_rate']} ｜ 单件利润：¥{e['profit_cny']}",
            f"- 关联达人：{e['creators']}（总 {e['creators_total']}） ｜ 周销量：{e['sales_week']}"
            f" ｜ 库存：{e['stock'] if e['stock'] is not None else '未知'}"
            + (f" ｜ 类目排名：{e['category_rank']}" if e.get("category_rank") else ""),
            f"- [FastMoss 详情]({e['fastmoss_url']}) ｜ [TikTok 商品页]({e['tiktok_url']})",
            "",
        ]
    md_path = raw_dir / "selected.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # 稳定路径副本，第二步以后固定从这里读最新一次
    data_dir = cfg.root / cfg.storage.data_dir
    (data_dir / "selected_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (data_dir / "selected_latest.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path

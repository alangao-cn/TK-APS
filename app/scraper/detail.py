"""详情页补抓：榜单接口只有一张主图、无描述；给 GPT 的数据需要多张图。
详情页打开后自己会调 /api/goods/v3/base?product_id=…（带 fm-sig 签名，只能靠真实导航截获），
其中 data.product.cover_list 是商品全部图片。"""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path

from .browser import open_persistent_browser
from .human import ensure_logged_in, pause_if_verification


async def _capture_base(page, url: str, timeout: float = 25000) -> dict:
    async with page.expect_response(lambda r: "/api/goods/v3/base" in r.url, timeout=timeout) as info:
        await page.goto(url, wait_until="domcontentloaded")
    resp = await info.value
    return await asyncio.wait_for(resp.json(), timeout=5)


def _to_int(v):
    """接口里数字经常是字符串（如 stock_count="210151"，断货时是 0）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract(product_raw: dict) -> dict:
    """从 base 接口的 data.product 里取补充字段。"""
    return {
        "image_urls": product_raw.get("cover_list") or [],
        "rating": _to_float(product_raw.get("product_rating")),
        "stock": _to_int(product_raw.get("stock_count")),
        "review_count": _to_int(product_raw.get("review_count")),
        "category_rank": _to_int(product_raw.get("category_rank")),
        "country_rank": _to_int(product_raw.get("country_rank")),
    }


async def enrich(products: list[dict], cfg, raw_dir: Path) -> int:
    """逐个打开入选商品的详情页，补齐多图与补充字段；返回成功条数。"""
    if not products:
        return 0
    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=cfg.selection.headless
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    detail_tpl = cfg.selection.detail_url_template
    ok = 0
    try:
        # 先借第一个详情页确认登录态（userInfo 需要在 fastmoss 域名下才能请求）
        first_url = detail_tpl.format(product_id=products[0].get("product_id"))
        await page.goto(first_url, wait_until="domcontentloaded")
        await pause_if_verification(page)
        await ensure_logged_in(page)

        for i, p in enumerate(products, 1):
            pid = str(p.get("product_id") or "")
            if not pid:
                continue
            cache = raw_dir / f"detail_{pid}.json"
            if cache.exists():
                try:
                    body = json.loads(cache.read_text(encoding="utf-8"))["body"]
                    product_raw = ((body.get("data") or {}).get("product")) or {}
                    if body.get("code") == 200 and product_raw:
                        p.update(_extract(product_raw))
                        ok += 1
                        continue  # 同一批数据重跑 export 时直接用缓存，不再开详情页
                except Exception:
                    pass  # 缓存坏了就重新抓

            url = detail_tpl.format(product_id=pid)
            try:
                try:
                    body = await _capture_base(page, url)
                except Exception:
                    await pause_if_verification(page)
                    await ensure_logged_in(page)
                    body = await _capture_base(page, url)
            except Exception as e:
                print(f"    [warn] {pid} 详情补抓失败，跳过：{type(e).__name__}: {e}")
                continue

            (raw_dir / f"detail_{pid}.json").write_text(
                json.dumps({"url": url, "captured_at": datetime.now().isoformat(timespec="seconds"),
                            "body": body}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            product_raw = ((body.get("data") or {}).get("product")) or {}
            if body.get("code") == 200 and product_raw:
                p.update(_extract(product_raw))
                ok += 1
                print(f"[详情] {i}/{len(products)} {pid}：{len(p.get('image_urls') or [])} 张图，"
                      f"评分 {p.get('rating')}，库存 {p.get('stock')}")
            else:
                print(f"    [warn] {pid} 详情接口返回异常 code={body.get('code')}")
            await asyncio.sleep(random.uniform(3, 6))
        return ok
    finally:
        await ctx.close()
        await pw.stop()

"""诊断：打开一个商品详情页，落盘全部接口响应，找多图和描述字段。"""

import asyncio
import json

from app.config import load_config
from app.scraper.browser import open_persistent_browser
from app.scraper.human import ensure_logged_in

PRODUCT_ID = "1735406761571026209"  # README 里的示例商品


async def main() -> None:
    cfg = load_config()
    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=False
    )
    page = ctx.pages[0]
    captured: list = []

    def on_response(resp) -> None:
        if "/api/" in resp.url and resp.request.resource_type in ("xhr", "fetch"):
            captured.append(resp)

    page.on("response", on_response)
    url = cfg.selection.detail_url_template.format(product_id=PRODUCT_ID)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    await ensure_logged_in(page)

    outdir = cfg.root / "data" / "raw" / "detail_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    hits = []
    for i, resp in enumerate(captured):
        try:
            body = await asyncio.wait_for(resp.json(), timeout=5)
        except Exception:
            continue
        endpoint = resp.url.split("?")[0].rsplit("/", 1)[-1]
        (outdir / f"{i:02d}_{endpoint}.json").write_text(
            json.dumps({"url": resp.url, "body": body}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        text = json.dumps(body, ensure_ascii=False)
        if PRODUCT_ID in text:
            hits.append((resp.url, endpoint, len(text)))

    print(f"共捕获 {len(captured)} 个接口，其中包含该商品ID 的 {len(hits)} 个：")
    for url, endpoint, size in hits:
        print(f"  {endpoint}  ({size} 字符)  {url[:110]}")
    print(f"全部已存到 {outdir}")

    await ctx.close()
    await pw.stop()


asyncio.run(main())

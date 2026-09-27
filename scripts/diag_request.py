"""诊断：抓一次真实 UI 点击发出的 popRank 请求头 + 分页控件结构。"""

import asyncio
import json

from app.config import load_config
from app.scraper.browser import open_persistent_browser
from app.scraper.collect import _click_label_radio, _hotlist_url, _wait_page_ready
from app.scraper.human import ensure_logged_in


async def main() -> None:
    cfg = load_config()
    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=False
    )
    page = ctx.pages[0]
    captured: list[dict] = []

    def on_request(req) -> None:
        if "popRank" in req.url:
            captured.append({
                "url": req.url,
                "method": req.method,
                "headers": dict(req.headers),
                "post_data": req.post_data,
            })

    page.on("request", on_request)
    await page.goto(_hotlist_url(cfg), wait_until="domcontentloaded")
    await _wait_page_ready(page)
    await ensure_logged_in(page)

    async with page.expect_response(lambda r: "popRank" in r.url, timeout=30000):
        await _click_label_radio(page, "周")
    await page.wait_for_timeout(2000)

    print("=== 真实请求（最近一条） ===")
    print(json.dumps(captured[-1], ensure_ascii=False, indent=2))

    pagination = await page.evaluate(
        """() => {
            const el = document.querySelector('.ant-pagination');
            return el ? el.textContent.trim().slice(0, 300) : '(no .ant-pagination)';
        }"""
    )
    size_changer = await page.evaluate(
        """() => {
            const el = document.querySelector('.ant-pagination-options');
            return el ? el.outerHTML.slice(0, 800) : '(no size changer)';
        }"""
    )
    print("=== 分页文字 ===", pagination)
    print("=== 分页大小选择器 ===", size_changer[:600])

    await ctx.close()
    await pw.stop()


asyncio.run(main())

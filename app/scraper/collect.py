"""采集流程：打开热销榜 → 人工登录/过验证 → 周榜 → 逐类目翻页，
截获页面自己请求到的接口 JSON，全部存 raw 目录（调整筛选规则不需要重新爬）。"""

import asyncio
import json
import random
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser import open_persistent_browser
from .human import ensure_logged_in, pause_if_verification

API_HINT = "/api/goods/"


def _rand_delay(cfg) -> None:
    lo, hi = cfg.selection.delay_seconds
    return asyncio.sleep(random.uniform(lo, hi))


def _hotlist_url(cfg) -> str:
    return cfg.selection.source_url.format(region=cfg.selection.region)


async def _wait_page_ready(page, timeout: float = 25000) -> None:
    """等 SPA 完成首次跳转（URL 会追加 v= 时间戳）并渲染出筛选项。
    注意 radio 的 input 是隐藏的，要等可见的 label。"""
    await page.wait_for_selector("label.ant-radio-button-wrapper", timeout=timeout)
    prev = None
    for _ in range(15):
        cur = page.url
        if cur == prev:
            break
        prev = cur
        await asyncio.sleep(1)


async def _click_label_radio(page, text: str) -> None:
    # antd 把 input 藏起来，真正可点的是外层 label
    loc = page.locator("label").filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$"))
    if await loc.count() == 0:
        loc = page.locator("label").filter(has_text=text)
    if await loc.count() == 0:
        raise RuntimeError(f"页面上找不到选项：{text}（当前页面：{page.url}）")
    await loc.first.wait_for(state="visible", timeout=10000)
    await loc.first.click()


async def _expand_categories(page) -> None:
    btn = page.get_by_role("button", name="展开")
    try:
        if await btn.count() > 0 and await btn.first.is_visible():
            await btn.first.click()
            await asyncio.sleep(1)
    except Exception:
        pass


async def _dump_radio_values(page) -> dict:
    return await page.evaluate(
        """() => {
            const out = {};
            document.querySelectorAll('input[type=radio]').forEach(r => {
                const label = r.closest('label');
                const text = label ? label.textContent.trim() : '';
                if (text && r.value) out[text] = r.value;
            });
            return out;
        }"""
    )


def _count_items(body) -> int:
    """从接口返回里找到商品列表数组，返回长度（结构变了也不至于崩）。"""
    def find_list(obj, depth=0):
        if depth > 5 or obj is None or not isinstance(obj, (dict, list)):
            return None
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj
        if isinstance(obj, dict):
            for key in ("list", "rank_list", "data", "items", "rows"):
                if key in obj:
                    found = find_list(obj[key], depth + 1)
                    if found:
                        return found
            for value in obj.values():
                found = find_list(value, depth + 1)
                if found:
                    return found
        return None

    items = find_list(body)
    return len(items) if items else 0


async def _expect_poprank(page, action, timeout: float = 30000) -> dict:
    """执行一个会触发榜单接口的操作，并截获该接口的响应。"""
    try:
        async with page.expect_response(lambda r: API_HINT in r.url, timeout=timeout) as info:
            await action()
        resp = await info.value
    except PlaywrightTimeoutError:
        # 超时大概率是弹了验证码，人工处理完页面会自动重试请求
        await pause_if_verification(page)
        async with page.expect_response(lambda r: API_HINT in r.url, timeout=60000) as info:
            pass
        resp = await info.value
    try:
        body = await resp.json()
    except Exception:
        body = {"_raw": (await resp.text())[:5000]}
    return {
        "url": resp.url,
        "params": dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(resp.url).query)),
        "body": body,
    }


async def _next_button(page):
    """返回可点击的“下一页”按钮；没有或已到最后一页返回 None。"""
    for sel in (".ant-pagination-next", ".ant-pagination li[title='下一页']",
                "button:has-text('下一页')"):
        loc = page.locator(sel)
        if await loc.count() > 0:
            btn = loc.first
            cls = (await btn.get_attribute("class") or "")
            aria = (await btn.get_attribute("aria-disabled") or "")
            if "disabled" not in cls and aria != "true":
                return btn
    return None


def _save(raw_dir: Path, name: str, payload: dict) -> None:
    path = raw_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    已保存 {path.relative_to(raw_dir.parent.parent)}")


async def _attach_api_recorder(page, raw_dir: Path) -> None:
    """全量落盘页面发出的 /api/ 请求与响应，probe 阶段用来发现接口细节。"""
    tasks: set = set()
    seq = 0

    async def _dump(resp) -> None:
        nonlocal seq
        try:
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            if "/api/" not in resp.url:
                return
            seq += 1
            parsed = urllib.parse.urlsplit(resp.url)
            endpoint = parsed.path.rsplit("/", 1)[-1] or "api"
            body = {"url": resp.url, "method": resp.request.method,
                    "post_data": resp.request.post_data,
                    "status": resp.status, "body": None}
            try:
                body["body"] = await resp.json()
            except Exception:
                body["body_raw"] = (await resp.text())[:3000]
            path = raw_dir / f"api_{seq:03d}_{endpoint}.json"
            path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # 记录失败不影响主流程
            print(f"    [warn] 记录接口失败: {e}")

    def on_response(resp) -> None:
        task = asyncio.create_task(_dump(resp))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    page.on("response", on_response)


def _iso_week(date_value: str | None = None) -> str:
    """接口的 date_value 形如 2026-38（ISO 周号），与页面点“周榜”后的默认值一致。"""
    from datetime import datetime

    d = datetime.now()
    cal = d.isocalendar()
    return f"{cal.year}-{cal.week:02d}"


async def _fetch_poprank_via_page(page, params: dict) -> dict:
    """在页面上下文里调接口（带上登录 cookie），返回 {status, body}。"""
    return await page.evaluate(
        """async (params) => {
            const qs = new URLSearchParams(params).toString();
            const r = await fetch('/api/goods/popRank?' + qs, {headers: {accept: 'application/json'}});
            let body = null;
            try { body = await r.json(); } catch (e) {}
            return {status: r.status, body: body, url: '/api/goods/popRank?' + qs};
        }""",
        params,
    )


async def collect_api(cfg, max_items: int = 500) -> Path:
    """API 直取模式：参数已实测（date_type=2 周榜 / l1_cid 类目 / 无签名），
    在登录后的页面里直接调接口翻页，比 UI 点击快且稳。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = cfg.root / cfg.storage.data_dir / "raw" / stamp
    raw_dir.mkdir(parents=True, exist_ok=True)

    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=cfg.selection.headless
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        print(f"[采集] 打开 {_hotlist_url(cfg)}（保持登录态）")
        await page.goto(_hotlist_url(cfg), wait_until="domcontentloaded")
        await _wait_page_ready(page)
        await pause_if_verification(page)
        await ensure_logged_in(page)

        radios = await _dump_radio_values(page)
        (raw_dir / "radio_values.json").write_text(
            json.dumps(radios, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        date_value = _iso_week()
        print(f"[采集] 周榜 date_value={date_value}")

        for cat in cfg.selection.categories:
            cid = radios.get(cat)
            if cid is None:
                raise RuntimeError(f"页面上找不到类目「{cat}」，可选：{[k for k in radios if k]}")
            base = {
                "order": "4,2", "region": cfg.selection.region,
                "date_type": "2", "date_value": date_value, "l1_cid": str(cid),
            }

            pagesize, page_no, got, total = 50, 1, 0, None
            while True:
                params = {
                    **base, "page": str(page_no), "pagesize": str(pagesize),
                    "_time": str(int(datetime.now().timestamp())),
                    "cnonce": str(random.randint(10_000_000, 99_999_999)),
                }
                result = await _fetch_poprank_via_page(page, params)
                body = result.get("body") or {}
                code = body.get("code")
                if result.get("status") != 200 or code != 200:
                    print(f"[需要人工] 接口返回异常（status={result.get('status')} code={code}），"
                          f"可能是登录过期或验证，处理后自动重试…")
                    await pause_if_verification(page)
                    await ensure_logged_in(page)
                    result = await _fetch_poprank_via_page(page, params)
                    body = result.get("body") or {}
                    if body.get("code") != 200:
                        raise RuntimeError(f"重试后仍失败：{cat} 第 {page_no} 页 code={body.get('code')}")

                data = body.get("data") or {}
                items = data.get("rank_list") or []
                if total is None:
                    total = data.get("total_count") or 0
                    print(f"[采集] 类目「{cat}」共 {total} 条，从第 1 页开始")
                # 接口可能悄悄把 pagesize 压到 10，按实际返回长度对齐后续翻页
                if page_no == 1 and 0 < len(items) < pagesize:
                    pagesize = len(items)
                    print(f"    pagesize 实际生效为 {pagesize}")

                got += len(items)
                payload = {"url": f"https://www.fastmoss.com{result.get('url', '')}",
                           "params": params, "body": body}
                _save(raw_dir, f"{cat}_p{page_no}.json", payload)
                print(f"    第 {page_no} 页：{len(items)} 条（累计 {got}/{total}）")

                if not items or got >= min(total or 10**9, max_items):
                    break
                page_no += 1
                await asyncio.sleep(random.uniform(2, 4))
            await _rand_delay(cfg)

        print(f"[采集] 完成，原始数据在 {raw_dir}")
        return raw_dir
    finally:
        await ctx.close()
        await pw.stop()


async def _jump_to_page(page, n: int) -> None:
    """用分页条的“跳至 N 页”输入框直接跳页，比连点“下一页”快得多。"""
    inp = page.locator(".ant-pagination-options-quick-jumper input")
    if await inp.count() == 0:
        raise RuntimeError("页面上没有跳页输入框")
    await inp.first.fill(str(n))
    await inp.first.press("Enter")


async def _total_pages(page) -> int:
    """分页条最后一个页码就是总页数（FastMoss 每类目最多 50 页）。"""
    try:
        return int(await page.evaluate(
            """() => {
                const items = [...document.querySelectorAll('.ant-pagination-item')];
                return items.length ? (Number(items[items.length - 1].title) || 0) : 0;
            }"""
        ))
    except Exception:
        return 0


async def collect(cfg, max_pages: int | None = None, record_all: bool = False) -> Path:
    """跑一遍选品采集，返回 raw 目录。record_all=True 时额外全量记录所有接口（probe 用）。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = cfg.root / cfg.storage.data_dir / "raw" / stamp
    raw_dir.mkdir(parents=True, exist_ok=True)

    pages = max_pages or cfg.selection.max_pages
    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=cfg.selection.headless
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    if record_all:
        all_api_dir = raw_dir / "all_api"
        all_api_dir.mkdir(parents=True, exist_ok=True)
        await _attach_api_recorder(page, all_api_dir)
    try:
        print(f"[采集] 打开 {_hotlist_url(cfg)}")
        await page.goto(_hotlist_url(cfg), wait_until="domcontentloaded")
        await _wait_page_ready(page)
        await pause_if_verification(page)
        await ensure_logged_in(page)
        await pause_if_verification(page)

        radios = await _dump_radio_values(page)
        (raw_dir / "radio_values.json").write_text(
            json.dumps(radios, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not radios:
            raise RuntimeError(f"页面就绪后仍读不到筛选项（当前页面：{page.url}）")
        print(f"[采集] 筛选项映射已保存（{len(radios)} 项，可查类目 ID）")

        print("[采集] 切换到 周榜 …")
        result = await _expect_poprank(page, lambda: _click_label_radio(page, "周"))
        _save(raw_dir, "period_week.json", result)
        print(f"    周榜参数: {result['params']}")
        await pause_if_verification(page)

        for cat in cfg.selection.categories:
            await _expand_categories(page)
            await _rand_delay(cfg)
            print(f"[采集] 类目「{cat}」第 1 页 …")
            result = await _expect_poprank(page, lambda: _click_label_radio(page, cat))
            _save(raw_dir, f"{cat}_p1.json", result)
            print(f"    {_count_items(result['body'])} 条 | 参数: {result['params']}")
            await pause_if_verification(page)

            total_pages = await _total_pages(page)
            if total_pages:
                pages = min(pages, total_pages)
            if total_pages:
                print(f"    该类目共 {total_pages} 页")
            for pn in range(2, pages + 1):
                await asyncio.sleep(random.uniform(2, 5))
                try:
                    result = await _expect_poprank(page, lambda n=pn: _jump_to_page(page, n))
                except Exception as e:
                    print(f"    [warn] 跳页失败（{e}），改用下一页按钮兜底")
                    btn = await _next_button(page)
                    if btn is None:
                        print(f"    没有更多页，停在 {pn - 1} 页")
                        break
                    result = await _expect_poprank(page, lambda b=btn: b.click())
                _save(raw_dir, f"{cat}_p{pn}.json", result)
                print(f"[采集] 类目「{cat}」第 {pn} 页：{_count_items(result['body'])} 条")
                await pause_if_verification(page)

        print(f"[采集] 完成，原始数据在 {raw_dir}")
        return raw_dir
    finally:
        await ctx.close()
        await pw.stop()


async def login_only(cfg) -> None:
    """只打开浏览器等人工登录，用于首次配置。"""
    pw, ctx = await open_persistent_browser(
        str(cfg.root / cfg.storage.browser_profile_dir), headless=cfg.selection.headless
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        await page.goto(_hotlist_url(cfg), wait_until="domcontentloaded")
        await pause_if_verification(page)
        await ensure_logged_in(page)
        print("[登录] 登录状态已保存到 browser_profile/，以后无需重复登录")
    finally:
        await ctx.close()
        await pw.stop()

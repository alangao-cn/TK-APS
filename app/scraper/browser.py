"""持久化浏览器：登录状态保存在 browser_profile/，人工登录一次后长期可用。"""

from playwright.async_api import async_playwright


async def open_persistent_browser(profile_dir: str, headless: bool):
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        profile_dir,
        headless=headless,
        viewport={"width": 1560, "height": 1000},
        locale="zh-CN",
        args=["--disable-blink-features=AutomationControlled"],
    )
    await ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return pw, ctx

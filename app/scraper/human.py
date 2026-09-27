"""人工介入点：登录（优先账号密码自动登录，失败转人工）、验证码弹窗暂停。
浏览器是有头模式，人工介入时直接在窗口里操作即可。"""

import asyncio
import os
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

VERIFY_MARKERS = ["安全验证", "拖动滑块", "请完成验证", "完成下方验证", "验证码"]


async def _visible_marker(page: Page) -> str | None:
    for marker in VERIFY_MARKERS:
        loc = page.get_by_text(marker, exact=False)
        try:
            if await loc.count() > 0 and await loc.first.is_visible():
                return marker
        except Exception:
            continue
    return None


async def pause_if_verification(page: Page, timeout: float = 600) -> None:
    marker = await _visible_marker(page)
    if not marker:
        return
    print(f"[需要人工] 检测到验证弹窗（{marker}），请在浏览器窗口中完成验证，完成后自动继续…")
    waited = 0.0
    while await _visible_marker(page):
        if page.is_closed():
            raise RuntimeError("浏览器窗口被关闭")
        if waited >= timeout:
            raise TimeoutError("等待人工验证超时")
        await asyncio.sleep(3)
        waited += 3
    print("[需要人工] 验证已通过，继续")


async def is_logged_in(page: Page) -> bool:
    try:
        res = await page.evaluate(
            """async () => {
                const r = await fetch('/api/user/index/userInfo?_time='
                    + Math.floor(Date.now() / 1000) + '&cnonce='
                    + Math.floor(Math.random() * 1e8),
                    { headers: { accept: 'application/json' } });
                return await r.json();
            }"""
        )
    except Exception:
        return False
    return bool(res.get("ext", {}).get("is_login"))


async def try_auto_login(page: Page, phone: str, password: str) -> bool:
    """按页面实际登录流程自动登录：
    右上角“登录/注册” → 弹窗切“手机号”tab → 点小按钮“密码登录” → 填手机号密码 → 提交。
    任何一步找不到预期元素或提交后未登录成功，都返回 False（交给人工）。
    """
    try:
        entry = page.get_by_text("登录/注册", exact=True).first
        await entry.wait_for(state="visible", timeout=5000)
        await entry.click()
        await asyncio.sleep(1.5)

        dialog = page.locator(".ant-modal, [role='dialog']").first
        await dialog.wait_for(state="visible", timeout=5000)

        # 第二个 tab：手机号短信登录
        tab = dialog.locator("[role='tab'], .ant-tabs-tab").filter(
            has_text=re.compile("手机|短信")
        ).first
        await tab.wait_for(state="visible", timeout=5000)
        if (await tab.get_attribute("aria-selected")) != "true":
            await tab.click()
            await asyncio.sleep(0.8)

        # tab 里很小的“密码登录”按钮
        pwd_switch = dialog.get_by_text("密码登录", exact=True).first
        await pwd_switch.wait_for(state="visible", timeout=5000)
        await pwd_switch.click()
        await asyncio.sleep(0.8)

        phone_input = dialog.get_by_placeholder(re.compile("手机号|手机号码|邮箱|账号")).first
        pwd_input = dialog.locator("input[type='password']").first
        await phone_input.wait_for(state="visible", timeout=5000)
        await phone_input.fill(phone)
        await pwd_input.fill(password)

        # 协议勾选（如有）
        checkbox = dialog.locator("label.ant-checkbox-wrapper").first
        if await checkbox.count() > 0:
            try:
                if not await checkbox.locator("input").is_checked():
                    await checkbox.click()
            except Exception:
                pass

        submit = dialog.get_by_role("button", name=re.compile("登\\s*录|立即登录")).first
        await submit.click()
        print("[登录] 已提交，等待登录结果…")

        for _ in range(8):
            await asyncio.sleep(4)
            await pause_if_verification(page)
            if await is_logged_in(page):
                return True
        return False
    except (PlaywrightTimeoutError, Exception) as e:
        print(f"[登录] 自动登录中止：{type(e).__name__}: {e}")
        return False


async def ensure_logged_in(page: Page, timeout: float = 900) -> None:
    if await is_logged_in(page):
        print("[登录] 已是登录状态")
        return
    phone = (os.environ.get("FASTMOSS_PHONE") or "").strip()
    password = (os.environ.get("FASTMOSS_PASSWORD") or "").strip()
    if phone and password:
        print("[登录] 尝试自动登录（账号密码）…")
        if await try_auto_login(page, phone, password):
            print("[登录] 自动登录成功")
            return
        print("[登录] 自动登录未成功，转人工")
    print("[需要人工] 请在打开的浏览器窗口中登录 FastMoss（微信扫码/手机号均可），脚本自动检测，无需其他操作…")
    waited = 0.0
    while not await is_logged_in(page):
        if page.is_closed():
            raise RuntimeError("浏览器窗口被关闭")
        if waited >= timeout:
            raise TimeoutError("等待登录超时（15 分钟）")
        await asyncio.sleep(5)
        waited += 5
    print("[登录] 登录成功")

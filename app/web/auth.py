"""网页登录：HMAC 签名的会话 Cookie（无额外依赖，够局域网使用）。

Cookie 值 = 过期时间戳.签名，密钥由 WEB_PASSWORD 派生，改密码即全部会话失效。
"""

import hashlib
import hmac
import os
import time

COOKIE_NAME = "tkaps_session"
MAX_AGE = 30 * 24 * 3600  # 30 天


def _secret() -> bytes:
    return hashlib.sha256(
        (os.environ.get("WEB_PASSWORD", "") + "::tk-aps-session").encode()
    ).digest()


def make_token() -> str:
    exp = str(int(time.time()) + MAX_AGE)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def check_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < time.time():
        return False
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)


def check_credentials(username: str, password: str) -> bool:
    ok_user = os.environ.get("WEB_USERNAME", "admin")
    ok_pass = os.environ.get("WEB_PASSWORD", "")
    if not ok_pass:
        return False  # .env 里没设 WEB_PASSWORD 时拒绝所有登录，避免裸奔
    return hmac.compare_digest(username, ok_user) and hmac.compare_digest(password, ok_pass)

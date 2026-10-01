"""登录 / 退出。"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..web import auth as auth_mod
from . import render

router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if auth_mod.check_token(request.cookies.get(auth_mod.COOKIE_NAME)):
        return RedirectResponse("/", status_code=302)
    return render(request, "login.html", {"err": request.query_params.get("err", "")})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...),
                next_url: str = Form("/")):
    if not auth_mod.check_credentials(username, password):
        return RedirectResponse("/login?err=账号或密码错误", status_code=303)
    if not next_url.startswith("/"):  # 只允许站内跳转
        next_url = "/"
    resp = RedirectResponse(next_url, status_code=303)
    resp.set_cookie(auth_mod.COOKIE_NAME, auth_mod.make_token(), max_age=auth_mod.MAX_AGE,
                    httponly=True, samesite="lax")
    resp.set_cookie("tkaps_user", username, max_age=auth_mod.MAX_AGE, httponly=False, samesite="lax")
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth_mod.COOKIE_NAME)
    resp.delete_cookie("tkaps_user")
    return resp

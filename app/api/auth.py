"""登录 / 登出 / 当前用户。"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from ..web import auth as auth_mod

router = APIRouter()


@router.post("/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not auth_mod.check_credentials(username, password):
        return JSONResponse({"detail": "账号或密码错误"}, status_code=401)
    resp = JSONResponse({"ok": True, "username": username})
    resp.set_cookie(auth_mod.COOKIE_NAME, auth_mod.make_token(), max_age=auth_mod.MAX_AGE,
                    httponly=True, samesite="lax")
    resp.set_cookie("tkaps_user", username, max_age=auth_mod.MAX_AGE, samesite="lax")
    return resp


@router.post("/auth/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth_mod.COOKIE_NAME)
    resp.delete_cookie("tkaps_user")
    return resp


@router.get("/auth/me")
async def me(request: Request):
    return {"username": request.cookies.get("tkaps_user", "")}

"""路由组装 + 共享的模板渲染助手。"""

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.templating import Jinja2Templates

from ..web import jobs as jobs_mod

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR),
                   autoescape=select_autoescape(["html"]))
templates = Jinja2Templates(env=_env)


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    ctx = ctx or {}
    ctx.setdefault("current_user", request.cookies.get("tkaps_user", ""))
    ctx.setdefault("msg", request.query_params.get("msg", ""))
    ctx.setdefault("err", request.query_params.get("err", ""))
    ctx.setdefault("running_total", jobs_mod.running_total())
    return templates.TemplateResponse(request=request, name=name, context=ctx, status_code=status_code)


def back(request: Request, msg: str = "", err: str = "") -> RedirectResponse:
    """动作完成后回到来的页面，带一条提示。"""
    target = request.headers.get("referer") or "/"
    sep = "&" if "?" in target else "?"
    if msg:
        target += f"{sep}msg={msg}"
    elif err:
        target += f"{sep}err={err}"
    return RedirectResponse(target, status_code=303)


from . import actions, api, auth, downloads, pages  # noqa: E402


all_routers = [auth.router, pages.router, actions.router, downloads.router, api.router]

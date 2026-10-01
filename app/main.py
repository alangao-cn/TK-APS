"""FastAPI 入口。

- /api/*     v11 JSON API（React SPA 消费），未登录返回 401
- /app/*     前端构建产物（frontend/dist），开发时用 Vite dev server 代理
- 其余路径    旧 Jinja 页面（v11 验收后移除），未登录 302 到 /login
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .db import make_engine
from .routes import all_routers
from .web import auth as auth_mod
from .web import jobs as jobs_mod


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：文件 → DB 同步（新批次/脚本/视频自动出现在页面），历史任务载入
    from . import sync as sync_mod
    try:
        sync_mod.sync_all(app.state.cfg, app.state.engine)
    except Exception as e:  # noqa: BLE001 - 同步失败不阻塞启动
        print(f"[启动] 文件同步失败：{e}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="TK_APS", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = load_config()
    app.state.engine = make_engine(app.state.cfg)
    jobs_mod.init_db(app.state.engine)

    @app.middleware("http")
    async def login_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith(("/static", "/login", "/favicon.ico", "/app", "/api/auth/login")):
            return await call_next(request)
        if not auth_mod.check_token(request.cookies.get(auth_mod.COOKIE_NAME)):
            if path.startswith("/api"):
                return JSONResponse({"detail": "未登录"}, status_code=401)
            return RedirectResponse(f"/login?next={path}", status_code=302)
        return await call_next(request)

    from .api import api_router
    app.include_router(api_router)

    for router in all_routers:  # 旧 Jinja 页面（过渡期保留）
        app.include_router(router)

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="spa")

    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"),
              name="static")
    return app


app = create_app()

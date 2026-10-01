"""FastAPI 入口。

- /api/*   JSON API（React SPA 消费），未登录返回 401，前端自己跳 #/login
- /*       前端构建产物（frontend/dist，Vite + React + antd），需要先 npm run build

Python 只做后端：API + 静态托管，一个进程。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .config import load_config
from .db import make_engine
from .web import auth as auth_mod
from .web import jobs as jobs_mod

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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
        # 页面本体/静态资源公开（未登录时前端路由自己跳登录）；只有 API 需要会话
        if path.startswith("/api") and not path.startswith("/api/auth/login"):
            if not auth_mod.check_token(request.cookies.get(auth_mod.COOKIE_NAME)):
                return JSONResponse({"detail": "未登录"}, status_code=401)
        return await call_next(request)

    app.include_router(api_router)

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="spa")
    else:
        print(f"[启动] 前端构建产物不存在：{DIST}（先 cd frontend && npm run build）")
    return app


app = create_app()

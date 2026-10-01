"""FastAPI 入口：uvicorn app.main:app --host 0.0.0.0 --port 8000（或 uv run cli.py serve）。"""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import load_config
from .routes import all_routers
from .web import auth as auth_mod

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    app = FastAPI(title="TK_APS", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = load_config()

    @app.middleware("http")
    async def login_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith(("/static", "/login", "/favicon.ico")):
            return await call_next(request)
        if not auth_mod.check_token(request.cookies.get(auth_mod.COOKIE_NAME)):
            return RedirectResponse(f"/login?next={path}", status_code=302)
        return await call_next(request)

    for router in all_routers:
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    return app


app = create_app()

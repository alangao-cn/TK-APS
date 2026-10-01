"""v11 JSON API（前端 React SPA 消费）。鉴权走全局中间件（/api/* 未登录返回 401）。"""

from fastapi import APIRouter

from . import auth, batches, jobs, media, products, scrape, scripts, settings, videos

api_router = APIRouter(prefix="/api")
for r in (auth.router, batches.router, products.router, scripts.router,
          videos.router, media.router, jobs.router, scrape.router, settings.router):
    api_router.include_router(r)

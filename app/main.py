from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.agent import router as agent_router
from app.api.routes.chat import router as chat_router
from app.api.routes.config import router as config_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.rag import router as rag_router
from app.api.routes.trace import router as trace_router
from app.core.config import settings
from app.core.logging import configure_logging, install_request_logging

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def mount_frontend(app: FastAPI) -> None:
    """挂载已构建的前端，让后端与前端共用一个入口（同一端口）。

    仅在 `frontend/dist/index.html` 存在时挂载，避免未构建前端时报错或影响测试。
    必须在所有 API 路由注册之后调用：根路径 `/` 的静态挂载会兜底未匹配请求，
    而 `/api/v1/*`、`/docs` 等已注册路由仍优先匹配。
    """
    if not (FRONTEND_DIST_DIR / "index.html").exists():
        return
    app.mount(
        "/",
        StaticFiles(directory=FRONTEND_DIST_DIR, html=True),
        name="frontend",
    )


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )
    install_request_logging(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agent_router, prefix=settings.api_prefix)
    app.include_router(chat_router, prefix=settings.api_prefix)
    app.include_router(config_router, prefix=settings.api_prefix)
    app.include_router(documents_router, prefix=settings.api_prefix)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(mcp_router, prefix=settings.api_prefix)
    app.include_router(rag_router, prefix=settings.api_prefix)
    app.include_router(trace_router, prefix=settings.api_prefix)
    mount_frontend(app)
    return app


app = create_app()

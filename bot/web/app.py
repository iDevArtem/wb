import logging
import os
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bot.core.database import close_db, init_db
from bot.web.routes import router as api_router

logger = logging.getLogger("bot.web.app")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB connection when running uvicorn independently
    try:
        await init_db()
        logger.info("MongoDB initialized for WebApp.")
    except Exception as exc:
        logger.warning("DB init in lifespan warning: %s", exc)
    yield
    try:
        await close_db()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="English Bot WebApp & Dashboard",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # CORS configuration for Telegram WebApp and web domain
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST API
    app.include_router(api_router)

    # Static assets
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/")
        async def serve_spa_index():
            index_file = STATIC_DIR / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
            return {"status": "ok", "message": "English Bot Web Dashboard API is running."}

    return app


app = create_app()

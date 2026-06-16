import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.services.live_scanner import (
    refresh_mock_scanner_once,
    run_mock_scanner_loop,
    stop_scanner_task,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await refresh_mock_scanner_once()
    scanner_task = asyncio.create_task(run_mock_scanner_loop())
    try:
        yield
    finally:
        await stop_scanner_task(scanner_task)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Crypto Perpetual Futures Arbitrage Scanner",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()

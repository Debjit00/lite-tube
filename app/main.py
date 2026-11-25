"""FastAPI entrypoint serving HTML pages, JSON APIs, and byte-range video streams."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import CATEGORIES, STATIC_DIR, TEMPLATES_DIR
from app.db import check_db_health, init_db, reset_db_pool
from app.routes.auth_routes import router as auth_router
from app.routes.media_routes import router as media_router
from app.routes.video_routes import router as video_router
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize database schema, seed demo data if empty, and close pool on exit."""
    init_db()
    seed_if_empty()
    try:
        yield
    finally:
        reset_db_pool()


app = FastAPI(title="LiteTube", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(auth_router)
app.include_router(video_router)
app.include_router(media_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Verify database connectivity."""
    return check_db_health()


@app.get("/", response_class=HTMLResponse)
def home_page(request: Request) -> HTMLResponse:
    """Render the home video feed page."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"categories": ["All", *CATEGORIES], "active_page": "home"},
    )


@app.get("/watch/{video_id}", response_class=HTMLResponse)
def watch_page(request: Request, video_id: str) -> HTMLResponse:
    """Render the video watch page."""
    return templates.TemplateResponse(
        request,
        "watch.html",
        {
            "video_id": video_id,
            "categories": ["All", *CATEGORIES],
            "active_page": "watch",
        },
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    """Render the creator upload studio page."""
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"categories": list(CATEGORIES), "active_page": "upload"},
    )

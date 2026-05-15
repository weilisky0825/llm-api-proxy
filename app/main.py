from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.logging.sqlite import SQLiteStore
from app.routes import anthropic, openai


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource, handling frozen environments."""
    if getattr(sys, 'frozen', False):
        return os.path.join(getattr(sys, '_MEIPASS'), relative)
    return os.path.abspath(relative)


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.logging.level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

TEMPLATES_DIR = Path(_resource_path("app/web/templates"))
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

app = FastAPI(title="LLM API Proxy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.auth.admin_middleware import AdminAuthMiddleware
from app.auth.user_middleware import UserAuthMiddleware

app.add_middleware(AdminAuthMiddleware)
app.add_middleware(UserAuthMiddleware)

# Register routes
app.include_router(openai.router)
app.include_router(anthropic.router)


@app.on_event("startup")
async def startup():
    store = SQLiteStore(settings.database.sqlite.path)
    await store._ensure_initialized()
    from app.proxy.forwarder import router
    router.initialize(settings.upstream)
    logging.info("LLM API Proxy started on %s:%d", settings.server.host, settings.server.port)


@app.on_event("shutdown")
async def shutdown():
    from app.proxy.forwarder import router
    await router.close_all()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "LLM API Proxy",
        "version": "0.1.0",
        "upstream": settings.upstream.provider,
        "endpoints": {
            "openai": ["/v1/chat/completions", "/v1/completions", "/v1/models"],
            "anthropic": ["/v1/messages", "/v1/messages/count_tokens", "/v1/models"],
            "health": "/health",
            "admin": "/admin",
        },
    }


def render_template(name: str, **context) -> HTMLResponse:
    template = jinja_env.get_template(f"{name}.html")
    return HTMLResponse(template.render(**context))


# Register web routes (after app is created)
from app.web import routes as web_routes
from app.web import api as web_api

app.include_router(web_routes.router)
app.include_router(web_api.router)
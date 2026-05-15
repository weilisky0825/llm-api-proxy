from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import yaml
import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.responses import JSONResponse
from pathlib import Path

from app.config import settings, CONFIG_PATH
from app.logging.sqlite import SQLiteStore
from app.proxy.forwarder import forwarder

router = APIRouter(prefix="/api/admin")


def get_store() -> SQLiteStore:
    return SQLiteStore(settings.database.sqlite.path)


# ---- Dashboard ----

@router.get("/dashboard")
async def dashboard_data():
    store = get_store()
    data = await store.get_dashboard()
    return data


# ---- Config ----

@router.get("/config")
async def get_config():
    if not CONFIG_PATH.exists():
        return {"error": "Config file not found"}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        content = f.read()
    raw = yaml.safe_load(content) or {}
    upstream = raw.get("upstream", {})
    providers = upstream.get("providers", [])
    # Backward compat: single provider mode
    if not providers and upstream.get("api_key"):
        providers = [{
            "name": "legacy",
            "provider": upstream.get("provider", "openai"),
            "api_key": upstream.get("api_key", ""),
            "base_url": upstream.get("base_url", ""),
            "timeout": upstream.get("timeout", 120),
            "models": [],
            "default": True,
        }]
    # Other YAML (without upstream.providers)
    other = {k: v for k, v in raw.items() if k != "upstream"}
    if upstream:
        other_upstream = {k: v for k, v in upstream.items() if k != "providers"}
        # Only include upstream in yaml_other if it has non-provider fields
        if other_upstream:
            other["upstream"] = other_upstream
    return {"providers": providers, "yaml_other": yaml.dump(other, default_flow_style=False) if other else ""}


@router.post("/config")
async def save_config(payload: dict):
    try:
        providers_data = payload.get("providers", [])
        yaml_other = payload.get("yaml_other", "")
        other = yaml.safe_load(yaml_other) or {}
        # yaml.safe_load may return a list or other non-dict type
        if not isinstance(other, dict):
            other = {}
        # Merge providers into upstream
        upstream_cfg = other.get("upstream")
        if upstream_cfg is None or not isinstance(upstream_cfg, dict):
            upstream_cfg = {}
        if providers_data:
            upstream_cfg["providers"] = providers_data
        other["upstream"] = upstream_cfg
        # Write
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(other, f, default_flow_style=False, allow_unicode=True)
        # Hot-reload - update global settings AND reinitialize router
        from app.config import reload_settings
        from app.proxy.forwarder import router
        new_settings = reload_settings()
        router.initialize(new_settings.upstream)
        return {"ok": True, "message": "Config saved and providers reloaded."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}")


# ---- Admin Auth ----

@router.post("/admin/login")
async def admin_login(payload: dict):
    from app.auth.password import verify_password
    from app.auth.session import COOKIE_NAME, create_session

    username = payload.get("username", "")
    password = payload.get("password", "")
    db_path = settings.database.sqlite.path

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT password_hash FROM admin_users WHERE username = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not verify_password(password, row[0]):
                return {"ok": False, "error": "用户名或密码错误"}

    session_id = await create_session(db_path, username)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE_NAME, session_id, httponly=True, samesite="lax", max_age=86400, path="/")
    return resp


@router.post("/admin/logout")
async def admin_logout(request: Request):
    from app.auth.session import COOKIE_NAME, delete_session
    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    await delete_session(db_path, session_id)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/admin/me")
async def admin_me(request: Request):
    from app.auth.session import COOKIE_NAME, get_session
    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    username = await get_session(db_path, session_id)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return {"username": username}


@router.post("/admin/password")
async def change_admin_password(request: Request, payload: dict):
    from app.auth.password import hash_password, verify_password
    from app.auth.session import COOKIE_NAME, get_session

    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    username = await get_session(db_path, session_id)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")

    old_pw = payload.get("old_password", "")
    new_pw = payload.get("new_password", "")
    if not new_pw or len(new_pw) < 6:
        return {"ok": False, "error": "密码至少6位"}

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT password_hash FROM admin_users WHERE username = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not verify_password(old_pw, row[0]):
                return {"ok": False, "error": "旧密码不正确"}

        await db.execute(
            "UPDATE admin_users SET password_hash = ? WHERE username = ?",
            (hash_password(new_pw), username),
        )
        await db.commit()
    return {"ok": True}


# ---- User Management ----

@router.get("/users")
async def list_users():
    db_path = settings.database.sqlite.path
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Reset quotas for new day
        await db.execute(
            "UPDATE users SET used_tokens = 0, quota_date = ? WHERE quota_date != ? AND quota_date != ''",
            (today, today),
        )
        await db.execute(
            "UPDATE users SET request_count = 0, request_date = ? WHERE request_date != ? AND request_date != ''",
            (today, today),
        )
        await db.commit()

        async with db.execute("SELECT * FROM users ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()
    users = []
    for r in rows:
        u = dict(r)
        u["masked_key"] = u["api_key"][:5] + "****" + u["api_key"][-4:] if u["api_key"] else ""
        u["quota_pct"] = round(u["used_tokens"] / u["daily_quota"] * 100, 1) if u["daily_quota"] > 0 else 0
        u["quota_over"] = u["used_tokens"] >= u["daily_quota"] > 0
        u.pop("api_key", None)  # Never expose full key
        users.append(u)
    return {"users": users}


@router.post("/users")
async def create_user(payload: dict):
    from app.models.user import generate_api_key
    db_path = settings.database.sqlite.path
    api_key = generate_api_key()
    name = payload.get("name", "")
    rate_limit = int(payload.get("rate_limit", 60))
    daily_quota = int(payload.get("daily_quota", 10000))
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO users (name, api_key, rate_limit, daily_quota) VALUES (?, ?, ?, ?)",
            (name, api_key, rate_limit, daily_quota),
        )
        await db.commit()
    return {"ok": True, "api_key": api_key}


@router.put("/users/{user_id}")
async def update_user(user_id: int, payload: dict):
    db_path = settings.database.sqlite.path
    name = payload.get("name", "")
    enabled = int(payload.get("enabled", 1))
    rate_limit = max(1, int(payload.get("rate_limit", 60)))
    daily_quota = max(0, int(payload.get("daily_quota", 10000)))
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE users SET name=?, enabled=?, rate_limit=?, daily_quota=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, enabled, rate_limit, daily_quota, user_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@router.post("/users/{user_id}/reset-key")
async def reset_user_key(user_id: int):
    from app.models.user import generate_api_key
    db_path = settings.database.sqlite.path
    new_key = generate_api_key()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE users SET api_key=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_key, user_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "api_key": new_key}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    db_path = settings.database.sqlite.path
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@router.post("/users/{user_id}/reset-quota")
async def reset_user_quota(user_id: int):
    db_path = settings.database.sqlite.path
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE users SET used_tokens=0, request_count=0, quota_date=?, request_date=? WHERE id=?",
            (today, today, user_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


# ---- Live Logs ----

@router.get("/logs/live")
async def logs_live():
    store = get_store()
    return StreamingResponse(
        live_log_stream(store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def live_log_stream(store):
    last_id = 0
    while True:
        await asyncio.sleep(1)
        logs = await store.get_latest_logs(10)
        new_logs = [l for l in logs if l["id"] > last_id]
        if new_logs:
            last_id = max(l["id"] for l in new_logs)
            for log in reversed(new_logs):
                data = json.dumps(log, ensure_ascii=False)
                yield f"data: {data}\n\n"


# ---- Log Query ----

@router.get("/logs")
async def query_logs(
    page: int = 1,
    page_size: int = 20,
    api_type: str = "",
    model: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    user_id: str = "",
):
    store = get_store()
    filters = {}
    if api_type:
        filters["api_type"] = api_type
    if model:
        filters["model"] = model
    if status:
        filters["status"] = int(status)
    if start:
        filters["start"] = start
    if end:
        filters["end"] = end
    if user_id:
        filters["user_id"] = int(user_id)
    logs, total = await store.query_logs(filters=filters, page=page, page_size=page_size)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ---- API Test ----

@router.post("/test")
async def api_test(payload: dict):
    api_format = payload.get("format", "openai")
    model = payload.get("model", "")
    content = payload.get("content", "")
    start = time.time()

    if api_format == "anthropic":
        provider_config = settings.upstream.get_provider_for_model(model)
        if provider_config.provider == "openai":
            from app.proxy.converter import anthropic_to_openai, convert_openai_response
            upstream_body = anthropic_to_openai({
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": payload.get("max_tokens", 1000),
                "temperature": payload.get("temperature", 1.0),
            })
            status, _, resp_body = await forwarder.send(model, "/chat/completions", upstream_body)
            resp_body = convert_openai_response(resp_body)
        else:
            upstream_body = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": payload.get("max_tokens", 1000),
                "temperature": payload.get("temperature", 1.0),
            }
            status, _, resp_body = await forwarder.send(model, "/messages", upstream_body)
    else:
        upstream_body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": payload.get("max_tokens", 1000),
            "temperature": payload.get("temperature", 1.0),
        }
        provider_config = settings.upstream.get_provider_for_model(model)
        if provider_config.provider == "anthropic":
            from app.proxy.converter import openai_to_anthropic, convert_anthropic_response
            upstream_body = openai_to_anthropic(upstream_body)
            status, _, resp_body = await forwarder.send(model, "/messages", upstream_body)
            resp_body = convert_anthropic_response(resp_body)
        else:
            status, _, resp_body = await forwarder.send(model, "/chat/completions", upstream_body)

    elapsed = int((time.time() - start) * 1000)
    return {"status": status, "elapsed_ms": elapsed, "response": resp_body}


# ---- Health ----

@router.get("/health")
async def health_check():
    import aiosqlite

    results = {}

    # Check upstream
    start = time.time()
    try:
        status_code, resp = await forwarder.get_models()
        elapsed = int((time.time() - start) * 1000)
        results["upstream"] = {
            "ok": status_code == 200,
            "status_code": status_code,
            "latency_ms": elapsed,
            "message": "OK" if status_code == 200 else f"HTTP {status_code}",
        }
    except Exception as e:
        results["upstream"] = {"ok": False, "latency_ms": -1, "message": str(e)}

    # Check database
    start = time.time()
    try:
        store = get_store()
        await store._ensure_initialized()
        async with aiosqlite.connect(store._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM api_logs") as cursor:
                row = await cursor.fetchone()
        elapsed = int((time.time() - start) * 1000)
        results["database"] = {
            "ok": True,
            "driver": settings.database.driver,
            "latency_ms": elapsed,
            "total_logs": row[0],
        }
    except Exception as e:
        results["database"] = {"ok": False, "latency_ms": -1, "message": str(e)}

    results["config"] = {
        "provider": settings.upstream.provider,
        "base_url": settings.upstream.base_url,
        "has_api_key": bool(settings.upstream.api_key),
    }

    return results


# ---- Stats ----

@router.get("/stats")
async def stats_data(group_by: str = "day"):
    store = get_store()
    data = await store.get_stats(group_by)
    return data
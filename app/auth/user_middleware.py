from __future__ import annotations

import aiosqlite
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth.rate_limiter import rate_limiter
from app.config import settings


class UserAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 只拦截 /v1/ 开头的 API 请求
        if not path.startswith("/v1/"):
            return await call_next(request)

        # 提取 Bearer token
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Missing API key. Use Authorization: Bearer <key>", "type": "auth_error"}},
            )

        api_key = auth[7:].strip()

        # 查询用户
        db_path = settings.database.sqlite.path
        user = None
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, api_key, enabled, rate_limit, daily_quota, used_tokens, quota_date, request_count, request_date FROM users WHERE api_key = ?",
                (api_key,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    user = dict(row)

        if not user:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Invalid API key", "type": "auth_error"}},
            )

        if not user["enabled"]:
            return JSONResponse(
                status_code=403,
                content={"error": {"message": "Account is disabled", "type": "auth_error"}},
            )

        # 检查每日配额
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_needs_reset = user["quota_date"] != today
        if quota_needs_reset:
            user["used_tokens"] = 0
            user["quota_date"] = today
        if user["daily_quota"] > 0 and user["used_tokens"] >= user["daily_quota"]:
            return JSONResponse(
                status_code=429,
                content={"error": {"message": "Daily token quota exceeded", "type": "quota_error"}},
            )

        # 检查每日请求数
        request_needs_reset = user["request_date"] != today
        if request_needs_reset:
            user["request_count"] = 0
            user["request_date"] = today

        # Persist quota/request date resets to DB
        if quota_needs_reset or request_needs_reset:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE users SET used_tokens = ?, quota_date = ?, request_count = ?, request_date = ? WHERE id = ?",
                    (user["used_tokens"], user["quota_date"], user["request_count"], user["request_date"], user["id"]),
                )
                await db.commit()

        # 检查速率限制
        if not rate_limiter.is_allowed(user["id"], user["rate_limit"]):
            return JSONResponse(
                status_code=429,
                content={"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
            )

        # 注入用户信息到 request.state
        request.state.user_id = user["id"]
        request.state.user_name = user["name"]

        return await call_next(request)


async def update_user_usage(user_id: int, tokens: int) -> None:
    """更新用户的 token 使用量和请求计数."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db_path = settings.database.sqlite.path
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET used_tokens = used_tokens + ?, request_count = request_count + 1, last_request_at = CURRENT_TIMESTAMP, quota_date = ?, request_date = ? WHERE id = ?",
            (tokens, today, today, user_id),
        )
        await db.commit()
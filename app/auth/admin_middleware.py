from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth.session import COOKIE_NAME, get_session
from app.config import settings

EXCLUDED_PATHS = {"/admin/login", "/admin/api/admin/login", "/admin/api/admin/logout"}


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 排除登录相关路径
        if path in EXCLUDED_PATHS or path.startswith("/admin/api/admin/login") or path.startswith("/admin/api/admin/logout"):
            return await call_next(request)

        # 只拦截 /admin 开头的路径
        if not path.startswith("/admin"):
            return await call_next(request)

        # 检查 session cookie
        session_id = request.cookies.get(COOKIE_NAME, "")
        if not session_id:
            return RedirectResponse(url="/admin/login", status_code=302)

        username = await get_session(settings.database.sqlite.path, session_id)
        if not username:
            return RedirectResponse(url="/admin/login", status_code=302)

        request.state.admin_user = username
        return await call_next(request)
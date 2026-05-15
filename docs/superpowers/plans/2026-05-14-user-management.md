# 用户管理与管理员认证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 添加管理员登录认证、用户 CRUD 管理、API Key 验证、配额/速率限制、日志按用户关联过滤。

**Architecture:** 新增 `app/auth/` 模块处理密码哈希、Session 管理、管理员中间件、用户 Key 中间件、速率限制。SQLite 新增 `admin_users`、`users`、`admin_sessions` 表，`api_logs` 表增加 `user_id`/`user_name` 列。Web 新增管理员登录页和用户管理页。

**Tech Stack:** FastAPI, aiosqlite, bcrypt, secrets, python-multipart, Alpine.js, Tailwind CSS

---

### Task 1: 依赖安装 + 数据库表创建

**Files:**
- Modify: `requirements.txt`
- Modify: `app/logging/sqlite.py`

- [ ] **Step 1: 添加 bcrypt 依赖**

在 `requirements.txt` 末尾添加：

```
bcrypt>=4.0.0
```

- [ ] **Step 2: 数据库表 SQL 常量**

在 `app/logging/sqlite.py` 顶部常量区域添加新表定义：

```python
CREATE_ADMIN_USERS = """
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE DEFAULT 'admin',
    password_hash TEXT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    api_key         TEXT NOT NULL UNIQUE,
    enabled         INTEGER NOT NULL DEFAULT 1,
    rate_limit      INTEGER NOT NULL DEFAULT 60,
    daily_quota     INTEGER NOT NULL DEFAULT 10000,
    used_tokens     INTEGER NOT NULL DEFAULT 0,
    quota_date      TEXT NOT NULL DEFAULT '',
    request_count   INTEGER NOT NULL DEFAULT 0,
    request_date    TEXT NOT NULL DEFAULT '',
    last_request_at DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ADMIN_SESSIONS = """
CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

ALTER_API_LOGS_USER = [
    "ALTER TABLE api_logs ADD COLUMN user_id INTEGER DEFAULT NULL;",
    "ALTER TABLE api_logs ADD COLUMN user_name TEXT DEFAULT '';",
    "CREATE INDEX IF NOT EXISTS idx_user_id ON api_logs(user_id);",
]
```

- [ ] **Step 3: `_ensure_initialized()` 中创建新表**

在 `app/logging/sqlite.py` 的 `_ensure_initialized()` 方法中，在 `CREATE_INDEXES` 执行后添加：

```python
async with aiosqlite.connect(self._db_path) as db:
    await db.execute(CREATE_ADMIN_USERS)
    await db.execute(CREATE_USERS)
    await db.execute(CREATE_ADMIN_SESSIONS)
    for stmt in ALTER_API_LOGS_USER:
        try:
            await db.execute(stmt)
        except Exception:
            pass  # column already exists
    await db.commit()
```

- [ ] **Step 4: 初始化默认管理员**

在同一方法末尾（commit 之后）添加：

```python
# 创建默认 admin (密码: admin123)
from app.auth.password import hash_password
default_hash = hash_password("admin123")
async with aiosqlite.connect(self._db_path) as db:
    await db.execute(
        "INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES ('admin', ?)",
        (default_hash,)
    )
    await db.commit()
```

- [ ] **Step 5: 验证**

重启服务，检查数据库表是否创建成功。

---

### Task 2: 密码哈希 + Session 管理模块

**Files:**
- Create: `app/auth/__init__.py`
- Create: `app/auth/password.py`
- Create: `app/auth/session.py`

- [ ] **Step 1: 创建 `app/auth/__init__.py`**

```python
```

（空文件）

- [ ] **Step 2: 创建 `app/auth/password.py`**

```python
from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """哈希密码，返回字符串."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hash_str: str) -> bool:
    """验证密码是否匹配哈希."""
    return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))
```

- [ ] **Step 3: 创建 `app/auth/session.py`**

```python
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite


SESSION_DURATION_HOURS = 24
COOKIE_NAME = "admin_session"


def generate_session_id() -> str:
    return secrets.token_urlsafe(48)


async def create_session(db_path: str, username: str) -> str:
    """创建新 session，返回 session_id."""
    session_id = generate_session_id()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO admin_sessions (session_id, username, expires_at) VALUES (?, ?, ?)",
            (session_id, username, expires_at),
        )
        await db.commit()
    return session_id


async def get_session(db_path: str, session_id: str) -> str | None:
    """验证 session，返回 username，无效返回 None."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT username FROM admin_sessions WHERE session_id = ? AND expires_at > ?",
            (session_id, now),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return row[0]


async def delete_session(db_path: str, session_id: str) -> None:
    """删除 session（登出）."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM admin_sessions WHERE session_id = ?", (session_id,))
        await db.commit()


async def clean_expired_sessions(db_path: str) -> None:
    """清理过期 session."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))
        await db.commit()
```

- [ ] **Step 4: 验证**

```bash
python -c "from app.auth.password import hash_password, verify_password; h=hash_password('test'); print(verify_password('test', h)); print(verify_password('wrong', h))"
```

Expected: `True` then `False`

---

### Task 3: 管理员认证中间件

**Files:**
- Create: `app/auth/admin_middleware.py`
- Modify: `app/main.py`

- [ ] **Step 1: 创建 `app/auth/admin_middleware.py`**

```python
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

        # 排除路径
        if path in EXCLUDED_PATHS or path.startswith("/admin/api/admin/login") or path.startswith("/admin/api/admin/logout"):
            return await call_next(request)

        # 排除静态资源/API 健康检查等
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
```

- [ ] **Step 2: 在 `app/main.py` 中注册中间件**

在 `app.add_middleware(CORSMiddleware, ...)` 之后添加：

```python
from app.auth.admin_middleware import AdminAuthMiddleware

app.add_middleware(AdminAuthMiddleware)
```

- [ ] **Step 3: 添加管理员登录路由**

在 `app/web/routes.py` 中添加：

```python
@router.get("/login")
async def login_page():
    return render_template("login", title="管理员登录", active="login")
```

- [ ] **Step 4: 验证**

重启服务后访问 `/admin`，应自动跳转到 `/admin/login`。

---

### Task 4: 管理员登录 API + 登录页

**Files:**
- Modify: `app/web/api.py`
- Create: `app/web/templates/login.html`

- [ ] **Step 1: 管理员登录 API**

在 `app/web/api.py` 中，在 `router = APIRouter(prefix="/api/admin")` 后添加：

```python
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
    from starlette.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE_NAME, session_id, httponly=True, samesite="lax", max_age=86400, path="/")
    return resp


@router.post("/admin/logout")
async def admin_logout():
    from app.auth.session import COOKIE_NAME, delete_session
    session_id = ""  # will be set by middleware from cookie
    db_path = settings.database.sqlite.path
    await delete_session(db_path, session_id)
    from starlette.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/admin/me")
async def admin_me():
    return {"username": "admin"}  # placeholder, actual from request.state
```

修正 `admin_logout` 需要读取 cookie：

```python
from fastapi import Request as FastAPIRequest

@router.post("/admin/logout")
async def admin_logout(request: FastAPIRequest):
    from app.auth.session import COOKIE_NAME, delete_session
    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    await delete_session(db_path, session_id)
    from starlette.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/admin/me")
async def admin_me(request: FastAPIRequest):
    from app.auth.session import COOKIE_NAME, get_session
    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    username = await get_session(db_path, session_id)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return {"username": username}
```

同时修正 `admin_login` 中 `aiosqlite` import 已在文件顶部存在。

- [ ] **Step 2: 创建登录页 `app/web/templates/login.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理员登录 - LLM API Proxy</title>
    <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 min-h-screen flex items-center justify-center">
    <div x-data="loginForm()" class="bg-gray-800 rounded-lg p-8 w-96 shadow-xl">
        <h1 class="text-2xl font-bold text-white text-center mb-2">LLM API Proxy</h1>
        <p class="text-gray-400 text-center text-sm mb-6">管理员登录</p>

        <form @submit.prevent="submit()">
            <div class="mb-4">
                <label class="block text-sm text-gray-400 mb-1">用户名</label>
                <input type="text" x-model="username" required
                       class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:border-blue-500 focus:outline-none">
            </div>
            <div class="mb-6">
                <label class="block text-sm text-gray-400 mb-1">密码</label>
                <input type="password" x-model="password" required
                       class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:border-blue-500 focus:outline-none">
            </div>

            <div x-show="error" x-cloak class="mb-4 text-red-400 text-sm text-center" x-text="error"></div>

            <button type="submit" :disabled="loading"
                    class="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded py-2 font-medium transition-colors">
                <span x-show="loading">登录中...</span>
                <span x-show="!loading">登录</span>
            </button>
        </form>
    </div>
</body>
</html>

<script>
function loginForm() {
    return {
        username: '',
        password: '',
        error: '',
        loading: false,
        async submit() {
            this.error = '';
            this.loading = true;
            try {
                const res = await fetch('/api/admin/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: this.username, password: this.password}),
                });
                const data = await res.json();
                if (data.ok) {
                    window.location.href = '/admin';
                } else {
                    this.error = data.error || '登录失败';
                }
            } catch {
                this.error = '网络错误';
            } finally {
                this.loading = false;
            }
        }
    };
}
</script>
```

- [ ] **Step 3: 验证**

重启服务，访问 `/admin/login`，用 `admin` / `admin123` 登录，成功后跳转到 `/admin`。

---

### Task 5: 用户管理 API

**Files:**
- Create: `app/models/user.py`
- Modify: `app/web/api.py`

- [ ] **Step 1: 创建 `app/models/user.py`**

```python
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone


def generate_api_key() -> str:
    return "sk-" + secrets.token_urlsafe(32)


@dataclass
class User:
    id: int | None = None
    name: str = ""
    api_key: str = ""
    enabled: int = 1
    rate_limit: int = 60
    daily_quota: int = 10000
    used_tokens: int = 0
    quota_date: str = ""
    request_count: int = 0
    request_date: str = ""
    last_request_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def masked_key(self) -> str:
        if not self.api_key:
            return ""
        return self.api_key[:5] + "****" + self.api_key[-4:]

    def quota_reset_needed(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.quota_date != today

    def request_reset_needed(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.request_date != today
```

- [ ] **Step 2: 用户 CRUD API**

在 `app/web/api.py` 中添加（在 `stats_data` 函数之后）：

```python
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
    rate_limit = int(payload.get("rate_limit", 60))
    daily_quota = int(payload.get("daily_quota", 10000))
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET name=?, enabled=?, rate_limit=?, daily_quota=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, enabled, rate_limit, daily_quota, user_id),
        )
        await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-key")
async def reset_user_key(user_id: int):
    from app.models.user import generate_api_key
    db_path = settings.database.sqlite.path
    new_key = generate_api_key()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET api_key=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_key, user_id),
        )
        await db.commit()
    return {"ok": True, "api_key": new_key}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    db_path = settings.database.sqlite.path
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-quota")
async def reset_user_quota(user_id: int):
    db_path = settings.database.sqlite.path
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET used_tokens=0, request_count=0, quota_date=?, request_date=? WHERE id=?",
            (today, today, user_id),
        )
        await db.commit()
    return {"ok": True}
```

需要 import datetime 到 api.py 顶部：

```python
from datetime import datetime, timezone
```

- [ ] **Step 3: 修改管理员 me API**

将 `admin_me` 从之前的占位实现改为从 cookie 读取：

```python
@router.get("/admin/me")
async def admin_me(request: Request):
    from app.auth.session import COOKIE_NAME, get_session
    db_path = settings.database.sqlite.path
    session_id = request.cookies.get(COOKIE_NAME, "")
    username = await get_session(db_path, session_id)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return {"username": username}
```

需要 `from fastapi import Request` — 检查文件顶部是否已有 `from fastapi import APIRouter, HTTPException`，添加 `Request`。

- [ ] **Step 4: 验证**

```bash
curl -s http://localhost:8000/api/admin/users -b "admin_session=<session_cookie>" | python -m json.tool
```

---

### Task 6: 用户 API Key 认证中间件 + 速率限制

**Files:**
- Create: `app/auth/rate_limiter.py`
- Create: `app/auth/user_middleware.py`
- Modify: `app/main.py`

- [ ] **Step 1: 创建 `app/auth/rate_limiter.py`**

```python
from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """滑动窗口速率限制器，内存实现."""

    def __init__(self, window_seconds: int = 60):
        self._window = window_seconds
        self._requests: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int, limit: int) -> bool:
        now = time.time()
        cutoff = now - self._window
        # 清理过期记录
        self._requests[user_id] = [t for t in self._requests[user_id] if t > cutoff]
        if len(self._requests[user_id]) >= limit:
            return False
        self._requests[user_id].append(now)
        return True

    def reset(self, user_id: int) -> None:
        self._requests.pop(user_id, None)

    def clear(self) -> None:
        self._requests.clear()


rate_limiter = RateLimiter()
```

- [ ] **Step 2: 创建 `app/auth/user_middleware.py`**

```python
from __future__ import annotations

import json

import aiosqlite
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
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if user["quota_date"] != today:
            user["used_tokens"] = 0
            user["quota_date"] = today
        if user["daily_quota"] > 0 and user["used_tokens"] >= user["daily_quota"]:
            return JSONResponse(
                status_code=429,
                content={"error": {"message": "Daily token quota exceeded", "type": "quota_error"}},
            )

        # 检查每日请求数
        if user["request_date"] != today:
            user["request_count"] = 0
            user["request_date"] = today

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
```

- [ ] **Step 3: 在 `app/main.py` 中注册用户中间件**

在 AdminAuthMiddleware 之后添加：

```python
from app.auth.user_middleware import UserAuthMiddleware

app.add_middleware(UserAuthMiddleware)
```

- [ ] **Step 4: 验证**

```bash
# 无效 key
curl -s http://localhost:8000/v1/chat/completions -H "Authorization: Bearer invalid" | python -m json.tool
# 应返回 401

# 创建用户后用真实 key 测试
curl -s http://localhost:8000/v1/chat/completions -H "Authorization: Bearer sk-xxx" -H "Content-Type: application/json" -d '{"model":"glm-5","messages":[{"role":"user","content":"hi"}]}' | python -m json.tool
```

---

### Task 7: 日志关联 user_id

**Files:**
- Modify: `app/logging/store.py`
- Modify: `app/logging/sqlite.py`
- Modify: `app/logging/middleware.py`
- Modify: `app/routes/openai.py`
- Modify: `app/routes/anthropic.py`

- [ ] **Step 1: `LogEntry` 增加字段**

在 `app/logging/store.py` 中：

```python
@dataclass
class LogEntry:
    request_id: str
    client_ip: str | None = None
    request_path: str = ""
    request_model: str = ""
    request_api: str = ""
    request_body: str = ""
    request_headers: str = ""
    user_id: int | None = None
    user_name: str = ""
```

- [ ] **Step 2: `middleware.py` 传递 user_id**

在 `app/logging/middleware.py` 的 `on_request` 方法中：

```python
async def on_request(self, request_data: dict[str, Any], client_ip: str, user_id: int | None = None, user_name: str = "") -> str:
    request_id = str(uuid.uuid4())
    entry = LogEntry(
        request_id=request_id,
        client_ip=client_ip,
        request_path=request_data.get("path", ""),
        request_model=request_data.get("model", ""),
        request_api=request_data.get("api_type", ""),
        request_body=request_data.get("body", ""),
        request_headers=request_data.get("headers", ""),
        user_id=user_id,
        user_name=user_name,
    )
    await self._store.log_request(entry)
    return request_id
```

- [ ] **Step 3: `sqlite.py` INSERT 语句更新**

在 `app/logging/sqlite.py` 中，修改 `INSERT_REQUEST`：

```python
INSERT_REQUEST = """
INSERT INTO api_logs (request_id, client_ip, request_path, request_model, request_api, request_body, request_headers, user_id, user_name)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
```

修改 `_worker()` 中的 request 分支：

```python
if op == "request":
    await db.execute(
        INSERT_REQUEST,
        (
            data["request_id"],
            data["client_ip"],
            data["request_path"],
            data["request_model"],
            data["request_api"],
            data["request_body"],
            data["request_headers"],
            data.get("user_id"),
            data.get("user_name", ""),
        ),
    )
```

修改 `log_request()` 方法：

```python
async def log_request(self, entry: LogEntry) -> None:
    await self._ensure_initialized()
    await self._queue.put(
        (
            "request",
            {
                "request_id": entry.request_id,
                "client_ip": entry.client_ip,
                "request_path": entry.request_path,
                "request_model": entry.request_model,
                "request_api": entry.request_api,
                "request_body": entry.request_body,
                "request_headers": entry.request_headers,
                "user_id": entry.user_id,
                "user_name": entry.user_name,
            },
        )
    )
```

- [ ] **Step 4: 路由中传递 user_id**

在 `app/routes/openai.py` 的 `chat_completions()` 中，修改 `mw.on_request` 调用：

```python
request_id = await mw.on_request(
    {
        "path": "/v1/chat/completions",
        "model": model,
        "api_type": "openai",
        "body": json.dumps(body),
        "headers": json.dumps({"content-type": "application/json"}),
    },
    client_ip=request.client.host if request.client else None,
    user_id=getattr(request.state, "user_id", None),
    user_name=getattr(request.state, "user_name", ""),
)
```

在 `app/routes/anthropic.py` 的 `messages()` 中同样修改：

```python
request_id = await mw.on_request(
    {
        "path": "/v1/messages",
        "model": model,
        "api_type": "anthropic",
        "body": json.dumps(body),
        "headers": json.dumps(
            {
                "content-type": "application/json",
                "anthropic-version": request.headers.get(
                    "anthropic-version", "2023-06-01"
                ),
            }
        ),
    },
    client_ip=request.client.host if request.client else None,
    user_id=getattr(request.state, "user_id", None),
    user_name=getattr(request.state, "user_name", ""),
)
```

- [ ] **Step 5: 更新配额计数器**

在 `app/routes/openai.py` 的 `chat_completions()` 中，成功响应后增加配额更新：

```python
# 在 await mw.on_response(...) 之后添加
if user_id := getattr(request.state, "user_id", None):
    from app.auth.user_middleware import update_user_usage
    await update_user_usage(user_id, usage.get("total_tokens", 0) if isinstance(usage, dict) else 0)
```

在 `app/auth/user_middleware.py` 末尾添加辅助函数：

```python
async def update_user_usage(user_id: int, tokens: int) -> None:
    """更新用户的 token 使用量和请求计数."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db_path = settings.database.sqlite.path
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET used_tokens = used_tokens + ?, request_count = request_count + 1, last_request_at = CURRENT_TIMESTAMP, quota_date = ?, request_date = ? WHERE id = ?",
            (tokens, today, today, user_id),
        )
        await db.commit()
```

同样在 `app/routes/anthropic.py` 的 `messages()` 末尾添加相同调用。

- [ ] **Step 6: 验证**

创建用户后用其 key 发送请求，检查数据库 `api_logs` 中 `user_id` 和 `user_name` 是否正确填充。

---

### Task 8: 日志查询按用户过滤

**Files:**
- Modify: `app/web/api.py`
- Modify: `app/logging/sqlite.py`

- [ ] **Step 1: `sqlite.py` query_logs 增加 user_id 过滤**

在 `app/logging/sqlite.py` 的 `query_logs` 方法中，filters 检查区域添加：

```python
if filters.get("user_id"):
    conditions.append("user_id = ?")
    params.append(int(filters["user_id"]))
```

- [ ] **Step 2: `api.py` logs API 接受 user_id 参数**

在 `app/web/api.py` 的 `query_logs` 函数签名中添加 `user_id: str = ""` 参数：

```python
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
```

在 filters 构建中添加：

```python
if user_id:
    filters["user_id"] = int(user_id)
```

- [ ] **Step 3: 验证**

```bash
curl "http://localhost:8000/api/admin/logs?user_id=1" -b "admin_session=<cookie>"
```

---

### Task 9: 用户管理前端页面

**Files:**
- Create: `app/web/templates/users.html`
- Modify: `app/web/routes.py`
- Modify: `app/web/templates/layout.html`

- [ ] **Step 1: 路由注册**

在 `app/web/routes.py` 中添加：

```python
@router.get("/users")
async def users_page():
    return render_template("users", title="用户管理", active="users")
```

- [ ] **Step 2: 导航栏添加**

在 `app/web/templates/layout.html` 侧边栏 `<nav>` 中，在"首页概览"之后添加：

```html
<a href="/admin/users" class="flex items-center px-4 py-2 rounded-lg transition-colors cursor-pointer {% if active == 'users' %}bg-blue-700 text-white{% else %}text-gray-300 hover:bg-gray-700 hover:text-white{% endif %}">
    <span class="mr-3">👥</span> 用户管理
</a>
```

- [ ] **Step 3: 创建 `app/web/templates/users.html`**

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="userManager()" x-init="init()">
    <!-- 添加用户按钮 -->
    <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold">用户列表</h3>
        <button @click="showCreate = true; form = {name: '', rate_limit: 60, daily_quota: 10000}"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium">添加用户</button>
    </div>

    <!-- 用户表格 -->
    <div class="bg-gray-800 rounded-lg overflow-hidden">
        <table class="w-full text-sm">
            <thead>
                <tr class="text-gray-400 border-b border-gray-700">
                    <th class="py-3 px-4 text-left">名称</th>
                    <th class="py-3 px-4 text-left">API Key</th>
                    <th class="py-3 px-4 text-center">状态</th>
                    <th class="py-3 px-4 text-center">速率</th>
                    <th class="py-3 px-4 text-left">配额使用</th>
                    <th class="py-3 px-4 text-center">操作</th>
                </tr>
            </thead>
            <tbody>
                <template x-for="u in users" :key="u.id">
                    <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
                        <td class="py-3 px-4 font-medium" x-text="u.name"></td>
                        <td class="py-3 px-4 font-mono text-xs text-gray-400" x-text="u.masked_key"></td>
                        <td class="py-3 px-4 text-center">
                            <button @click="toggleUser(u)"
                                    class="px-2 py-1 rounded text-xs"
                                    :class="u.enabled ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'"
                                    x-text="u.enabled ? '启用' : '禁用'"></button>
                        </td>
                        <td class="py-3 px-4 text-center font-mono text-xs" x-text="u.rate_limit + '/min'"></td>
                        <td class="py-3 px-4">
                            <div class="flex items-center gap-2">
                                <div class="flex-1 bg-gray-900 rounded-full h-2 overflow-hidden">
                                    <div class="h-full rounded-full transition-all"
                                         :class="u.quota_over ? 'bg-red-500' : 'bg-green-500'"
                                         :style="'width: ' + Math.min(u.quota_pct, 100) + '%'"></div>
                                </div>
                                <span class="text-xs text-gray-400 font-mono whitespace-nowrap"
                                      x-text="u.daily_quota > 0 ? u.used_tokens + '/' + u.daily_quota : '不限'"></span>
                            </div>
                        </td>
                        <td class="py-3 px-4 text-center">
                            <div class="flex gap-1 justify-center">
                                <button @click="resetKey(u)" class="text-blue-400 hover:text-blue-300 text-xs">重置Key</button>
                                <button @click="resetQuota(u)" class="text-yellow-400 hover:text-yellow-300 text-xs">重置配额</button>
                                <button @click="editUser(u)" class="text-gray-400 hover:text-gray-300 text-xs">编辑</button>
                                <button @click="deleteUser(u)" class="text-red-400 hover:text-red-300 text-xs">删除</button>
                            </div>
                        </td>
                    </tr>
                </template>
            </tbody>
        </table>
        <div x-show="users.length === 0" class="py-8 text-center text-gray-500">暂无用户</div>
    </div>

    <!-- 创建/编辑弹窗 -->
    <div x-show="showCreate || showEdit" x-cloak class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showCreate = false; showEdit = false">
        <div class="bg-gray-800 rounded-lg p-6 w-[450px]">
            <h3 class="text-lg font-bold mb-4" x-text="showCreate ? '添加用户' : '编辑用户'"></h3>
            <div class="space-y-3">
                <div>
                    <label class="text-xs text-gray-400">名称</label>
                    <input type="text" x-model="form.name" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                </div>
                <div x-show="showCreate">
                    <label class="text-xs text-gray-400">速率限制（次/分钟）</label>
                    <input type="number" x-model.number="form.rate_limit" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                </div>
                <div x-show="showCreate">
                    <label class="text-xs text-gray-400">每日 Token 配额（0=不限）</label>
                    <input type="number" x-model.number="form.daily_quota" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                </div>
                <div x-show="showEdit">
                    <label class="text-xs text-gray-400">速率限制（次/分钟）</label>
                    <input type="number" x-model.number="form.rate_limit" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                </div>
                <div x-show="showEdit">
                    <label class="text-xs text-gray-400">每日 Token 配额（0=不限）</label>
                    <input type="number" x-model.number="form.daily_quota" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                </div>
                <div x-show="showEdit">
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" x-model="form.enabled" class="rounded">
                        启用
                    </label>
                </div>
            </div>
            <div class="flex justify-end gap-2 mt-4">
                <button @click="showCreate = false; showEdit = false" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">取消</button>
                <button @click="saveUser()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm">保存</button>
            </div>
        </div>
    </div>

    <!-- 重置 Key 弹窗 -->
    <div x-show="showKey" x-cloak class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showKey = false">
        <div class="bg-gray-800 rounded-lg p-6 w-[500px]">
            <h3 class="text-lg font-bold mb-2">新 API Key</h3>
            <p class="text-xs text-gray-400 mb-3">请妥善保存，关闭后将无法再次查看完整 Key。</p>
            <div class="bg-gray-900 rounded p-3 font-mono text-sm select-all" x-text="newKey"></div>
            <div class="flex justify-end gap-2 mt-4">
                <button @click="copyKey()" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">复制</button>
                <button @click="showKey = false" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm">关闭</button>
            </div>
        </div>
    </div>
</div>

<script>
function userManager() {
    return {
        users: [],
        showCreate: false, showEdit: false, showKey: false,
        form: { name: '', rate_limit: 60, daily_quota: 10000, enabled: true },
        newKey: '', editingId: null,
        async init() { await this.loadUsers(); },
        async loadUsers() {
            const res = await fetch('/api/admin/users');
            const data = await res.json();
            this.users = data.users;
        },
        async saveUser() {
            if (this.showCreate) {
                const res = await fetch('/api/admin/users', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(this.form),
                });
                const data = await res.json();
                if (data.ok) {
                    this.newKey = data.api_key;
                    this.showCreate = false;
                    this.showKey = true;
                    await this.loadUsers();
                }
            } else if (this.showEdit) {
                await fetch(`/api/admin/users/${this.editingId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(this.form),
                });
                this.showEdit = false;
                await this.loadUsers();
            }
        },
        async toggleUser(u) {
            await fetch(`/api/admin/users/${u.id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({...u, enabled: u.enabled ? 0 : 1}),
            });
            await this.loadUsers();
        },
        async resetKey(u) {
            const res = await fetch(`/api/admin/users/${u.id}/reset-key`, {method: 'POST'});
            const data = await res.json();
            if (data.ok) {
                this.newKey = data.api_key;
                this.showKey = true;
            }
        },
        async resetQuota(u) {
            await fetch(`/api/admin/users/${u.id}/reset-quota`, {method: 'POST'});
            await this.loadUsers();
        },
        async deleteUser(u) {
            if (!confirm(`确定删除用户 "${u.name}"？`)) return;
            await fetch(`/api/admin/users/${u.id}`, {method: 'DELETE'});
            await this.loadUsers();
        },
        editUser(u) {
            this.form = {name: u.name, rate_limit: u.rate_limit, daily_quota: u.daily_quota, enabled: !!u.enabled};
            this.editingId = u.id;
            this.showEdit = true;
        },
        async copyKey() {
            await navigator.clipboard.writeText(this.newKey);
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 4: 验证**

重启服务后访问 `/admin/users`，创建用户，验证 Key 弹窗、表格、配额进度条。

---

### Task 10: 日志查询用户过滤 + 管理员密码修改

**Files:**
- Modify: `app/web/templates/logs.html`
- Modify: `app/web/api.py`
- Modify: `app/web/templates/layout.html`

- [ ] **Step 1: 日志过滤器添加用户下拉框**

在 `app/web/templates/logs.html` 的过滤器区域（API 类型 select 之前）添加：

```html
<div>
    <label class="text-xs text-gray-400">用户</label>
    <select x-model="filters.user_id" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
        <option value="">全部</option>
        <template x-for="u in userList" :key="u.id">
            <option :value="u.id" x-text="u.name"></option>
        </template>
    </select>
</div>
```

在 Alpine.js 组件中添加 `userList` 状态和加载：

```javascript
userList: [],
```

在 `init()` 中添加：

```javascript
this.loadUsers();
```

添加方法：

```javascript
async loadUsers() {
    try {
        const res = await fetch('/api/admin/users');
        const data = await res.json();
        this.userList = data.users;
    } catch {}
},
```

修改 `search()` 中的 params 构建，确保 user_id 不为空字符串时才传递：

```javascript
const params = new URLSearchParams({
    page: this.page,
    page_size: this.pageSize,
});
for (const [k, v] of Object.entries(this.filters)) {
    if (v) params.set(k, v);
}
```

- [ ] **Step 2: 导航栏添加管理员信息**

在 `app/web/templates/layout.html` 的 `</aside>` 之后、`<main>` 之前添加：

```html
<div class="fixed top-0 right-0 z-40 flex items-center gap-3 p-3">
    <span class="text-sm text-gray-400">管理员: <span id="adminName">...</span></span>
    <button onclick="adminLogout()" class="text-sm text-gray-400 hover:text-white">退出</button>
</div>
```

在 `</body>` 之前添加脚本：

```html
<script>
async function loadAdminName() {
    try {
        const res = await fetch('/api/admin/admin/me');
        const data = await res.json();
        const el = document.getElementById('adminName');
        if (el) el.textContent = data.username;
    } catch {}
}
async function adminLogout() {
    await fetch('/api/admin/admin/logout', {method: 'POST'});
    window.location.href = '/admin/login';
}
document.addEventListener('DOMContentLoaded', loadAdminName);
</script>
```

- [ ] **Step 3: 管理员密码修改 API**

在 `app/web/api.py` 中添加：

```python
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
```

- [ ] **Step 4: 系统配置页添加密码修改**

在 `app/web/templates/config.html` 底部（YAML 编辑器之后、保存按钮之前或之后）添加密码修改区域：

```html
<!-- 修改管理员密码 -->
<div class="bg-gray-800 rounded-lg p-4 mt-4">
    <h3 class="text-sm font-semibold mb-3">修改管理员密码</h3>
    <div x-data="changePassword()" class="space-y-2">
        <div class="flex gap-3 items-end">
            <div class="flex-1">
                <label class="text-xs text-gray-400">旧密码</label>
                <input type="password" x-model="oldPassword" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
            </div>
            <div class="flex-1">
                <label class="text-xs text-gray-400">新密码</label>
                <input type="password" x-model="newPassword" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
            </div>
            <button @click="submit()" class="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded text-sm font-medium">修改密码</button>
        </div>
        <div x-show="msg" x-cloak class="text-sm" :class="ok ? 'text-green-400' : 'text-red-400'" x-text="msg"></div>
    </div>
</div>
```

在 config.html 的 `<script>` 部分（或末尾）添加 Alpine 组件：

```javascript
function changePassword() {
    return {
        oldPassword: '', newPassword: '', msg: '', ok: false,
        async submit() {
            this.msg = '';
            const res = await fetch('/api/admin/admin/password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({old_password: this.oldPassword, new_password: this.newPassword}),
            });
            const data = await res.json();
            if (data.ok) {
                this.ok = true;
                this.msg = '密码修改成功';
                this.oldPassword = '';
                this.newPassword = '';
            } else {
                this.ok = false;
                this.msg = data.error || '修改失败';
            }
        }
    };
}
```

- [ ] **Step 5: 验证**

1. 访问 `/admin/users` 查看用户列表
2. 创建用户，复制 Key，用 Key 发送请求
3. 访问 `/admin/logs`，按用户过滤
4. 访问 `/admin/config`，修改管理员密码
5. 用新密码重新登录

---

### Task 11: 验证与收尾

- [ ] **Step 1: 完整流程验证**

1. `uvicorn app.main:app --reload` 启动服务
2. 访问 `http://localhost:8000/admin` → 跳转登录页
3. 用 `admin` / `admin123` 登录
4. 进入用户管理，创建测试用户
5. 复制用户 Key，发送 API 请求
6. 进入日志查询，按用户过滤查看
7. 修改管理员密码，退出后用新密码登录

- [ ] **Step 2: 安全验证**

1. 无 session cookie 访问 `/admin/*` → 跳转登录
2. 无效 Key 访问 `/v1/*` → 401
3. 禁用用户 Key 访问 → 403
4. 超配额访问 → 429

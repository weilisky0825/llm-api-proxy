# Web Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web management panel for the LLM API Proxy with dashboard, config management, real-time logs, log query, API testing, health check, and request statistics pages.

**Architecture:** FastAPI serves Jinja2 HTML templates; HTMX handles partial page updates and SSE for real-time logs; Alpine.js manages client state; Chart.js renders statistics charts.

**Tech Stack:** Python, FastAPI, Jinja2, HTMX, Alpine.js, Chart.js, Tailwind CSS, aiosqlite

---

## File Map

### New Files
- `app/web/__init__.py` — Package init
- `app/web/routes.py` — HTML page routes (dashboard, config, live, logs, test, health, stats)
- `app/web/api.py` — JSON API routes (/api/admin/*)
- `app/web/templates/layout.html` — Base layout with sidebar navigation
- `app/web/templates/dashboard.html` — Dashboard page
- `app/web/templates/config.html` — Config editor page
- `app/web/templates/live.html` — Real-time logs page
- `app/web/templates/logs.html` — Log query page
- `app/web/templates/test.html` — API test page
- `app/web/templates/health.html` — Health check page
- `app/web/templates/stats.html` — Statistics page

### Modified Files
- `app/logging/sqlite.py` — Add query methods: get_latest_logs, query_logs, get_stats, get_dashboard
- `app/main.py` — Register web routes, add Jinja2 template support
- `requirements.txt` — Add jinja2, python-multipart
- `app/config.py` — No changes needed; config saved via YAML write in api.py

---

### Task 1: Dependencies & SQLite Query Methods

**Files:**
- Modify: `requirements.txt` — add jinja2, python-multipart
- Modify: `app/logging/sqlite.py` — add 4 query methods

- [ ] **Step 1: Add new dependencies**

Add to `requirements.txt` (append):
```
jinja2>=3.1.0
python-multipart>=0.0.9
```

- [ ] **Step 2: Add SQLite query methods**

Append to `app/logging/sqlite.py`:

```python
    async def _connect(self):
        """Get a direct connection for reads (not queued)."""
        return await aiosqlite.connect(self._db_path)

    async def get_latest_logs(self, limit: int = 50) -> list[dict]:
        await self._ensure_initialized()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM api_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def query_logs(
        self,
        filters: dict | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        await self._ensure_initialized()
        conditions = []
        params: list = []

        if filters:
            if filters.get("api_type"):
                conditions.append("request_api = ?")
                params.append(filters["api_type"])
            if filters.get("model"):
                conditions.append("request_model = ?")
                params.append(filters["model"])
            if filters.get("status") is not None:
                code = int(filters["status"])
                if code == 0:
                    conditions.append("status_code IS NULL")
                else:
                    conditions.append("status_code = ?")
                    params.append(code)
            if filters.get("start"):
                conditions.append("timestamp >= ?")
                params.append(filters["start"])
            if filters.get("end"):
                conditions.append("timestamp <= ?")
                params.append(filters["end"])

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Count
            async with db.execute(
                f"SELECT COUNT(*) FROM api_logs {where}", params
            ) as cursor:
                row = await cursor.fetchone()
                total = row[0]

            # Data
            offset = (page - 1) * page_size
            async with db.execute(
                f"SELECT * FROM api_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows], total

    async def get_stats(self, group_by: str) -> list[dict]:
        await self._ensure_initialized()
        group_map = {
            "hour": "strftime('%Y-%m-%d %H:00', timestamp)",
            "day": "strftime('%Y-%m-%d', timestamp)",
            "model": "request_model",
            "path": "request_path",
            "api": "request_api",
        }
        expr = group_map.get(group_by, "strftime('%Y-%m-%d', timestamp)")
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT {expr} AS bucket,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS success,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(AVG(response_time_ms), 0) AS avg_ms
                FROM api_logs
                GROUP BY {expr}
                ORDER BY bucket DESC
                LIMIT 100
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_dashboard(self) -> dict:
        await self._ensure_initialized()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Today's stats
            async with db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS success,
                    COALESCE(SUM(total_tokens), 0) AS tokens,
                    COALESCE(AVG(response_time_ms), 0) AS avg_ms
                FROM api_logs
                WHERE date(timestamp) = date('now')
                """
            ) as cursor:
                row = await cursor.fetchone()
                today = dict(row)

            # Recent 20
            async with db.execute(
                "SELECT * FROM api_logs ORDER BY id DESC LIMIT 20"
            ) as cursor:
                recent = [dict(r) for r in await cursor.fetchall()]

            # Overall total
            async with db.execute("SELECT COUNT(*) AS total FROM api_logs") as cursor:
                overall = dict(await cursor.fetchone())

        return {
            "today_total": today["total"],
            "today_success": today["success"],
            "today_tokens": today["tokens"],
            "today_avg_ms": round(today["avg_ms"], 0),
            "overall_total": overall["total"],
            "recent": recent,
        }
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt app/logging/sqlite.py
git commit -m "feat: add SQLite query methods for admin panel"
```

---

### Task 2: App Integration — Jinja2 + Web Router Registration

**Files:**
- Modify: `app/main.py` — add Jinja2, register web routes

- [ ] **Step 1: Update main.py**

Replace the entire `app/main.py` with:

```python
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.logging.sqlite import SQLiteStore
from app.routes import anthropic, openai

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.logging.level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

TEMPLATES_DIR = Path(__file__).parent / "web" / "templates"
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

# Register routes
app.include_router(openai.router)
app.include_router(anthropic.router)

# Will be imported after app is defined to avoid circular imports
# (web routes need the app for Jinja2 rendering)


@app.on_event("startup")
async def startup():
    # Initialize SQLite store to create tables
    store = SQLiteStore(settings.database.sqlite.path)
    await store._ensure_initialized()
    logging.info("LLM API Proxy started on %s:%d", settings.server.host, settings.server.port)


@app.on_event("shutdown")
async def shutdown():
    from app.proxy.forwarder import forwarder
    await forwarder.close()


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
```

- [ ] **Step 2: Commit**

```bash
git add app/main.py
git commit -m "feat: add Jinja2 template support and admin endpoint in root"
```

---

### Task 3: Layout Template + Web Package

**Files:**
- Create: `app/web/__init__.py`
- Create: `app/web/templates/layout.html`

- [ ] **Step 1: Create package init**

`app/web/__init__.py` — empty file.

- [ ] **Step 2: Create layout template**

`app/web/templates/layout.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - LLM API Proxy</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
    {% if charts %}
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7"></script>
    {% endif %}
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        [x-cloak] { display: none !important; }
        .sidebar-link.active { @apply bg-blue-700 text-white; }
        .sidebar-link { @apply flex items-center px-4 py-2 rounded-lg text-gray-300 hover:bg-gray-700 hover:text-white transition-colors cursor-pointer; }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div class="flex">
        <!-- Sidebar -->
        <aside class="w-56 bg-gray-800 min-h-screen p-4 fixed left-0 top-0">
            <div class="mb-8 px-2">
                <h1 class="text-lg font-bold text-white">LLM API Proxy</h1>
                <p class="text-xs text-gray-400">v0.1.0</p>
            </div>
            <nav class="space-y-1">
                <a href="/admin" class="sidebar-link {% if active == 'dashboard' %}active{% endif %}">
                    <span class="mr-3">📊</span> 首页概览
                </a>
                <a href="/admin/config" class="sidebar-link {% if active == 'config' %}active{% endif %}">
                    <span class="mr-3">⚙️</span> 系统配置
                </a>
                <a href="/admin/live" class="sidebar-link {% if active == 'live' %}active{% endif %}">
                    <span class="mr-3">📡</span> 实时日志
                </a>
                <a href="/admin/logs" class="sidebar-link {% if active == 'logs' %}active{% endif %}">
                    <span class="mr-3">🔍</span> 日志查询
                </a>
                <a href="/admin/test" class="sidebar-link {% if active == 'test' %}active{% endif %}">
                    <span class="mr-3">🧪</span> API 测试
                </a>
                <a href="/admin/health" class="sidebar-link {% if active == 'health' %}active{% endif %}">
                    <span class="mr-3">💚</span> 健康检查
                </a>
                <a href="/admin/stats" class="sidebar-link {% if active == 'stats' %}active{% endif %}">
                    <span class="mr-3">📈</span> 请求统计
                </a>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="ml-56 flex-1 p-6">
            <h2 class="text-2xl font-bold mb-6 text-white">{{ title }}</h2>
            {% block content %}{% endblock %}
        </main>
    </div>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add app/web/__init__.py app/web/templates/layout.html
git commit -m "feat: add sidebar layout template with navigation"
```

---

### Task 4: Dashboard Page + API

**Files:**
- Create: `app/web/templates/dashboard.html`
- Create: `app/web/routes.py` — dashboard HTML route + /api/admin/dashboard
- Create: `app/web/api.py` — will contain all JSON APIs; start with dashboard

- [ ] **Step 1: Create dashboard template**

`app/web/templates/dashboard.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="dashboard()" x-init="init()">
    <!-- Stats Cards -->
    <div class="grid grid-cols-4 gap-4 mb-6">
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="text-sm text-gray-400">今日请求</div>
            <div class="text-3xl font-bold mt-1" x-text="data.today_total">—</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="text-sm text-gray-400">成功率</div>
            <div class="text-3xl font-bold mt-1" x-text="data.today_success_rate + '%'">—</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="text-sm text-gray-400">今日 Token 用量</div>
            <div class="text-3xl font-bold mt-1" x-text="data.today_tokens.toLocaleString()">—</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="text-sm text-gray-400">平均响应时间</div>
            <div class="text-3xl font-bold mt-1" x-text="data.today_avg_ms + 'ms'">—</div>
        </div>
    </div>

    <!-- Recent Requests -->
    <div class="bg-gray-800 rounded-lg p-4">
        <h3 class="text-lg font-semibold mb-4">最近请求</h3>
        <div class="overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-gray-400 border-b border-gray-700">
                        <th class="pb-2 text-left">时间</th>
                        <th class="pb-2 text-left">API</th>
                        <th class="pb-2 text-left">模型</th>
                        <th class="pb-2 text-left">路径</th>
                        <th class="pb-2 text-left">状态</th>
                        <th class="pb-2 text-left">耗时</th>
                        <th class="pb-2 text-left">Token</th>
                    </tr>
                </thead>
                <tbody>
                    <template x-for="r in data.recent" :key="r.request_id">
                        <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
                            <td class="py-2 font-mono text-xs" x-text="r.timestamp"></td>
                            <td class="py-2" x-text="r.request_api"></td>
                            <td class="py-2 font-mono text-xs" x-text="r.request_model || '—'"></td>
                            <td class="py-2 font-mono text-xs" x-text="r.request_path"></td>
                            <td class="py-2">
                                <span class="px-2 py-0.5 rounded text-xs"
                                      :class="r.status_code === 200 ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'"
                                      x-text="r.status_code || '—'"></span>
                            </td>
                            <td class="py-2 font-mono" x-text="r.response_time_ms ? r.response_time_ms + 'ms' : '—'"></td>
                            <td class="py-2 font-mono" x-text="r.total_tokens || '—'"></td>
                        </tr>
                    </template>
                </tbody>
            </table>
            <div x-show="data.recent.length === 0" class="py-8 text-center text-gray-500">
                暂无请求记录
            </div>
        </div>
    </div>
</div>

<script>
function dashboard() {
    return {
        data: { today_total: 0, today_success: 0, today_tokens: 0, today_avg_ms: 0, today_success_rate: 0, recent: [] },
        async init() {
            try {
                const res = await fetch('/api/admin/dashboard');
                const d = await res.json();
                this.data = d;
                if (d.today_total > 0) {
                    this.data.today_success_rate = Math.round((d.today_success / d.today_total) * 100);
                }
            } catch (e) {
                console.error('Failed to load dashboard:', e);
            }
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 2: Create routes.py**

`app/web/routes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.main import render_template

router = APIRouter(prefix="/admin")


@router.get("")
async def admin_index():
    return RedirectResponse(url="/admin/dashboard")


@router.get("/dashboard")
async def dashboard():
    return render_template("dashboard.html", title="首页概览", active="dashboard")


@router.get("/config")
async def config_page():
    return render_template("config.html", title="系统配置", active="config")


@router.get("/live")
async def live_page():
    return render_template("live.html", title="实时日志", active="live")


@router.get("/logs")
async def logs_page():
    return render_template("logs.html", title="日志查询", active="logs")


@router.get("/test")
async def test_page():
    return render_template("test.html", title="API 测试", active="test")


@router.get("/health")
async def health_page():
    return render_template("health.html", title="健康检查", active="health")


@router.get("/stats")
async def stats_page():
    return render_template("stats.html", title="请求统计", active="stats", charts=True)
```

- [ ] **Step 3: Create api.py — start with dashboard API**

`app/web/api.py`:

```python
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter

from app.config import settings
from app.logging.sqlite import SQLiteStore

router = APIRouter(prefix="/api/admin")


def get_store() -> SQLiteStore:
    return SQLiteStore(settings.database.sqlite.path)


# ---- Dashboard ----

@router.get("/dashboard")
async def dashboard_data():
    store = get_store()
    data = await store.get_dashboard()
    return data
```

- [ ] **Step 4: Register routers in main.py**

Add to the end of `app/main.py`:

```python
# Register web routes (after app is created)
from app.web import routes as web_routes  # noqa: E402
from app.web import api as web_api       # noqa: E402

app.include_router(web_routes.router)
app.include_router(web_api.router)
```

- [ ] **Step 5: Restart and test**

```bash
# Restart uvicorn
curl -s http://localhost:8000/admin/dashboard | head -5
# Should return HTML
curl -s http://localhost:8000/api/admin/dashboard | python -m json.tool
# Should return dashboard JSON
```

- [ ] **Step 6: Commit**

```bash
git add app/web/routes.py app/web/api.py app/web/templates/dashboard.html app/main.py
git commit -m "feat: add dashboard page and API"
```

---

### Task 5: Config Page + API

**Files:**
- Create: `app/web/templates/config.html`
- Modify: `app/web/api.py` — add config GET/POST endpoints

- [ ] **Step 1: Add config API endpoints**

Append to `app/web/api.py`:

```python
import yaml
from pathlib import Path
from fastapi import HTTPException

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


@router.get("/config")
async def get_config():
    if not CONFIG_PATH.exists():
        return {"error": "Config file not found"}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        content = f.read()
    return {"yaml": content}


@router.post("/config")
async def save_config(payload: dict):
    try:
        # Validate YAML
        yaml.safe_load(payload["yaml"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(payload["yaml"])
    return {"ok": True, "message": "Config saved. Restart service to apply changes."}
```

- [ ] **Step 2: Create config template**

`app/web/templates/config.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="configPage()" x-init="init()">
    <div class="bg-gray-800 rounded-lg p-4 mb-4">
        <p class="text-sm text-gray-400 mb-2">
            编辑 YAML 配置文件，保存后重启服务生效。
        </p>
        <textarea
            x-model="yaml"
            class="w-full h-96 bg-gray-900 text-green-400 font-mono text-sm p-4 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
            spellcheck="false"
        ></textarea>
    </div>
    <div class="flex gap-3">
        <button
            @click="save()"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors"
        >保存配置</button>
        <span x-show="msg" x-text="msg" class="text-sm py-2"
              :class="msgOk ? 'text-green-400' : 'text-red-400'"></span>
    </div>
</div>

<script>
function configPage() {
    return {
        yaml: '',
        msg: '',
        msgOk: true,
        async init() {
            const res = await fetch('/api/admin/config');
            const data = await res.json();
            this.yaml = data.yaml || '';
        },
        async save() {
            this.msg = '保存中...';
            const res = await fetch('/api/admin/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ yaml: this.yaml })
            });
            const data = await res.json();
            if (res.ok) {
                this.msg = data.message;
                this.msgOk = true;
            } else {
                this.msg = data.detail || '保存失败';
                this.msgOk = false;
            }
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/config.html app/web/api.py
git commit -m "feat: add config editor page and API"
```

---

### Task 6: Live Logs Page + SSE API

**Files:**
- Create: `app/web/templates/live.html`
- Modify: `app/web/api.py` — add SSE endpoint

- [ ] **Step 1: Add SSE endpoint**

Append to `app/web/api.py`:

```python
from fastapi.responses import StreamingResponse


@router.get("/logs/live")
async def logs_live():
    store = get_store()
    return StreamingResponse(
        live_log_stream(store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def live_log_stream(store: SQLiteStore):
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
```

- [ ] **Step 2: Create live logs template**

`app/web/templates/live.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="liveLogs()" x-init="start()">
    <div class="flex items-center gap-3 mb-4">
        <span class="text-sm text-gray-400">实时显示最近的请求</span>
        <span class="flex items-center gap-1 text-sm" :class="running ? 'text-green-400' : 'text-red-400'">
            <span class="w-2 h-2 rounded-full" :class="running ? 'bg-green-400 animate-pulse' : 'bg-red-400'"></span>
            <span x-text="running ? '监听中' : '已停止'"></span>
        </span>
        <button @click="clear()" class="text-xs text-gray-400 hover:text-white ml-4">清空</button>
    </div>
    <div class="bg-gray-800 rounded-lg p-4 max-h-[600px] overflow-y-auto font-mono text-xs space-y-1">
        <template x-for="log in logs" :key="log.request_id">
            <div class="flex items-center gap-3 py-1 border-b border-gray-700/30">
                <span class="text-gray-500 w-24" x-text="log.timestamp"></span>
                <span class="px-1.5 py-0.5 rounded text-xs"
                      :class="log.status_code === 200 ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'"
                      x-text="log.status_code || '...'"></span>
                <span class="text-blue-400 w-20" x-text="log.request_api"></span>
                <span class="text-yellow-300 truncate max-w-[150px]" x-text="log.request_model"></span>
                <span class="text-gray-300 truncate max-w-[200px]" x-text="log.request_path"></span>
                <span class="text-gray-500" x-text="log.response_time_ms ? log.response_time_ms + 'ms' : ''"></span>
            </div>
        </template>
        <div x-show="logs.length === 0" class="py-8 text-center text-gray-500">
            等待请求...
        </div>
    </div>
</div>

<script>
function liveLogs() {
    return {
        logs: [],
        running: false,
        source: null,
        start() {
            this.running = true;
            this.source = new EventSource('/api/admin/logs/live');
            this.source.onmessage = (e) => {
                const log = JSON.parse(e.data);
                this.logs.unshift(log);
                if (this.logs.length > 100) this.logs.pop();
            };
            this.source.onerror = () => {
                this.running = false;
                this.source.close();
            };
        },
        clear() {
            this.logs = [];
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/live.html app/web/api.py
git commit -m "feat: add live logs page with SSE streaming"
```

---

### Task 7: Log Query Page + API

**Files:**
- Create: `app/web/templates/logs.html`
- Modify: `app/web/api.py` — add log query endpoint

- [ ] **Step 1: Add log query API**

Append to `app/web/api.py`:

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
    logs, total = await store.query_logs(filters=filters, page=page, page_size=page_size)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
```

- [ ] **Step 2: Create logs template**

`app/web/templates/logs.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="logsQuery()" x-init="init()">
    <!-- Filters -->
    <div class="bg-gray-800 rounded-lg p-4 mb-4">
        <div class="grid grid-cols-5 gap-3">
            <div>
                <label class="text-xs text-gray-400">API 类型</label>
                <select x-model="filters.api_type" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
                    <option value="">全部</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                </select>
            </div>
            <div>
                <label class="text-xs text-gray-400">模型</label>
                <input type="text" x-model="filters.model" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
            </div>
            <div>
                <label class="text-xs text-gray-400">状态码</label>
                <select x-model="filters.status" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
                    <option value="">全部</option>
                    <option value="200">200</option>
                    <option value="400">400</option>
                    <option value="404">404</option>
                    <option value="500">500</option>
                </select>
            </div>
            <div>
                <label class="text-xs text-gray-400">开始时间</label>
                <input type="datetime-local" x-model="filters.start" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
            </div>
            <div>
                <label class="text-xs text-gray-400">结束时间</label>
                <input type="datetime-local" x-model="filters.end" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
            </div>
        </div>
        <div class="mt-3">
            <button @click="search()" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium">查询</button>
        </div>
    </div>

    <!-- Results Table -->
    <div class="bg-gray-800 rounded-lg p-4">
        <div class="overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-gray-400 border-b border-gray-700">
                        <th class="pb-2 text-left">时间</th>
                        <th class="pb-2 text-left">API</th>
                        <th class="pb-2 text-left">模型</th>
                        <th class="pb-2 text-left">路径</th>
                        <th class="pb-2 text-left">状态</th>
                        <th class="pb-2 text-left">耗时</th>
                        <th class="pb-2 text-left">Token</th>
                        <th class="pb-2 text-left">操作</th>
                    </tr>
                </thead>
                <tbody>
                    <template x-for="r in logs" :key="r.request_id">
                        <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
                            <td class="py-2 font-mono text-xs" x-text="r.timestamp"></td>
                            <td class="py-2" x-text="r.request_api"></td>
                            <td class="py-2 font-mono text-xs" x-text="r.request_model || '—'"></td>
                            <td class="py-2 font-mono text-xs" x-text="r.request_path"></td>
                            <td class="py-2">
                                <span class="px-2 py-0.5 rounded text-xs"
                                      :class="r.status_code === 200 ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'"
                                      x-text="r.status_code || '—'"></span>
                            </td>
                            <td class="py-2 font-mono" x-text="r.response_time_ms ? r.response_time_ms + 'ms' : '—'"></td>
                            <td class="py-2 font-mono" x-text="r.total_tokens || '—'"></td>
                            <td class="py-2">
                                <button @click="viewDetail(r)" class="text-blue-400 hover:text-blue-300 text-xs">详情</button>
                            </td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>

        <!-- Pagination -->
        <div class="flex items-center justify-between mt-4 text-sm text-gray-400">
            <span>共 <span x-text="total"></span> 条</span>
            <div class="flex gap-2">
                <button @click="page > 1 && (page--, search())" :disabled="page <= 1"
                        class="px-3 py-1 rounded border border-gray-700 disabled:opacity-50 hover:bg-gray-700">上一页</button>
                <span class="py-1">第 <span x-text="page"></span> 页</span>
                <button @click="page < totalPages && (page++, search())" :disabled="page >= totalPages"
                        class="px-3 py-1 rounded border border-gray-700 disabled:opacity-50 hover:bg-gray-700">下一页</button>
            </div>
        </div>
    </div>

    <!-- Detail Modal -->
    <div x-show="showDetail" x-cloak class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showDetail = false">
        <div class="bg-gray-800 rounded-lg p-6 w-[800px] max-h-[80vh] overflow-y-auto">
            <h3 class="text-lg font-bold mb-4">请求详情</h3>
            <div class="space-y-3 text-sm font-mono">
                <div><span class="text-gray-400">Request ID:</span> <span x-text="detail.request_id"></span></div>
                <div><span class="text-gray-400">请求体:</span>
                    <pre class="bg-gray-900 p-3 rounded mt-1 overflow-x-auto text-xs" x-text="detail.request_body"></pre>
                </div>
                <div><span class="text-gray-400">响应体:</span>
                    <pre class="bg-gray-900 p-3 rounded mt-1 overflow-x-auto text-xs" x-text="detail.response_body"></pre>
                </div>
            </div>
            <button @click="showDetail = false" class="mt-4 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">关闭</button>
        </div>
    </div>
</div>

<script>
function logsQuery() {
    return {
        filters: { api_type: '', model: '', status: '', start: '', end: '' },
        logs: [],
        total: 0,
        page: 1,
        totalPages: 0,
        pageSize: 20,
        showDetail: false,
        detail: {},
        init() { this.search(); },
        async search() {
            const params = new URLSearchParams({
                page: this.page,
                page_size: this.pageSize,
                ...Object.fromEntries(Object.entries(this.filters).filter(([k, v]) => v))
            });
            const res = await fetch('/api/admin/logs?' + params);
            const data = await res.json();
            this.logs = data.logs;
            this.total = data.total;
            this.totalPages = data.total_pages;
        },
        viewDetail(log) {
            this.detail = log;
            this.showDetail = true;
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/logs.html app/web/api.py
git commit -m "feat: add log query page with filter and pagination"
```

---

### Task 8: API Test Page + API

**Files:**
- Create: `app/web/templates/test.html`
- Modify: `app/web/api.py` — add test endpoint

- [ ] **Step 1: Add API test endpoint**

Append to `app/web/api.py`:

```python
from app.proxy.forwarder import forwarder
from app.proxy.converter import openai_to_anthropic, convert_anthropic_response


@router.post("/test")
async def api_test(payload: dict):
    api_format = payload.get("format", "openai")
    model = payload.get("model", "")
    content = payload.get("content", "")

    import time
    start = time.time()

    if api_format == "anthropic":
        # Client sends Anthropic format, convert to upstream format
        if settings.upstream.provider == "openai":
            from app.proxy.converter import anthropic_to_openai
            upstream_body = anthropic_to_openai({
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": payload.get("max_tokens", 1000),
                "temperature": payload.get("temperature", 1.0),
            })
            status, _, resp_body = await forwarder.send("/chat/completions", upstream_body)
            from app.proxy.converter import convert_openai_response
            resp_body = convert_openai_response(resp_body)
        else:
            upstream_body = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": payload.get("max_tokens", 1000),
                "temperature": payload.get("temperature", 1.0),
            }
            status, _, resp_body = await forwarder.send("/messages", upstream_body)
    else:
        # Client sends OpenAI format
        upstream_body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": payload.get("max_tokens", 1000),
            "temperature": payload.get("temperature", 1.0),
        }
        if settings.upstream.provider == "anthropic":
            upstream_body = openai_to_anthropic(upstream_body)
            status, _, resp_body = await forwarder.send("/messages", upstream_body)
            resp_body = convert_anthropic_response(resp_body)
        else:
            status, _, resp_body = await forwarder.send("/chat/completions", upstream_body)

    elapsed = int((time.time() - start) * 1000)
    return {
        "status": status,
        "elapsed_ms": elapsed,
        "response": resp_body,
    }
```

- [ ] **Step 2: Create API test template**

`app/web/templates/test.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="apiTest()" x-init="models = [{{ models|default('""')|tojson }}]">
    <div class="grid grid-cols-3 gap-4 mb-4">
        <div class="bg-gray-800 rounded-lg p-4">
            <label class="text-sm text-gray-400">API 格式</label>
            <select x-model="format" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm">
                <option value="openai">OpenAI (chat/completions)</option>
                <option value="anthropic">Anthropic (messages)</option>
            </select>
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <label class="text-sm text-gray-400">模型</label>
            <input type="text" x-model="model" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm" placeholder="glm-5">
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <label class="text-sm text-gray-400">Max Tokens</label>
            <input type="number" x-model="maxTokens" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm" value="1000">
        </div>
    </div>

    <div class="bg-gray-800 rounded-lg p-4 mb-4">
        <label class="text-sm text-gray-400">内容</label>
        <textarea x-model="content" rows="4" class="w-full mt-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm font-mono" placeholder="Hello"></textarea>
    </div>

    <button @click="send()" :disabled="loading"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50">
        <span x-show="!loading">发送请求</span>
        <span x-show="loading">发送中...</span>
    </button>

    <div x-show="result" class="mt-4 bg-gray-800 rounded-lg p-4">
        <div class="flex gap-4 text-sm text-gray-400 mb-3">
            <span>状态: <span x-text="result.status" :class="result.status === 200 ? 'text-green-400' : 'text-red-400'"></span></span>
            <span>耗时: <span x-text="result.elapsed_ms + 'ms'"></span></span>
        </div>
        <pre class="bg-gray-900 p-4 rounded text-xs font-mono overflow-x-auto whitespace-pre-wrap" x-text="JSON.stringify(result.response, null, 2)"></pre>
    </div>
</div>

<script>
function apiTest() {
    return {
        format: 'openai',
        model: 'glm-5',
        maxTokens: 1000,
        content: 'Hello',
        loading: false,
        result: null,
        async send() {
            this.loading = true;
            this.result = null;
            const res = await fetch('/api/admin/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    format: this.format,
                    model: this.model,
                    content: this.content,
                    max_tokens: parseInt(this.maxTokens)
                })
            });
            this.result = await res.json();
            this.loading = false;
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/test.html app/web/api.py
git commit -m "feat: add API test page"
```

---

### Task 9: Health Check Page + API

**Files:**
- Create: `app/web/templates/health.html`
- Modify: `app/web/api.py` — add health check endpoint

- [ ] **Step 1: Add health check API**

Append to `app/web/api.py`:

```python
import httpx


@router.get("/health")
async def health_check():
    results = {}

    # Check upstream
    start = __import__("time").time()
    try:
        status_code, resp = await forwarder.get_models()
        elapsed = int((__import__("time").time() - start) * 1000)
        results["upstream"] = {
            "ok": status_code == 200,
            "status_code": status_code,
            "latency_ms": elapsed,
            "message": "OK" if status_code == 200 else f"HTTP {status_code}",
        }
    except Exception as e:
        results["upstream"] = {"ok": False, "latency_ms": -1, "message": str(e)}

    # Check database
    start = __import__("time").time()
    try:
        store = get_store()
        await store._ensure_initialized()
        async with __import__("aiosqlite", fromlist=[""]).connect(store._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM api_logs") as cursor:
                row = await cursor.fetchone()
        elapsed = int((__import__("time").time() - start) * 1000)
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
```

- [ ] **Step 2: Create health template**

`app/web/templates/health.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="healthCheck()" x-init="init()">
    <div class="space-y-4">
        <!-- Upstream Status -->
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-lg font-semibold">上游 API</h3>
                <span class="px-2 py-1 rounded text-sm"
                      :class="data.upstream?.ok ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'"
                      x-text="data.upstream?.ok ? '正常' : '异常'"></span>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
                <div><span class="text-gray-400">提供商:</span> <span x-text="data.config?.provider"></span></div>
                <div><span class="text-gray-400">延迟:</span> <span x-text="data.upstream?.latency_ms + 'ms'"></span></div>
                <div><span class="text-gray-400">Base URL:</span> <span class="font-mono text-xs" x-text="data.config?.base_url"></span></div>
                <div><span class="text-gray-400">API Key:</span> <span x-text="data.config?.has_api_key ? '已配置' : '未配置'"></span></div>
            </div>
            <div x-show="data.upstream?.message" class="mt-2 text-xs font-mono text-red-400" x-text="data.upstream?.message"></div>
        </div>

        <!-- Database Status -->
        <div class="bg-gray-800 rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-lg font-semibold">数据库</h3>
                <span class="px-2 py-1 rounded text-sm"
                      :class="data.database?.ok ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'"
                      x-text="data.database?.ok ? '正常' : '异常'"></span>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
                <div><span class="text-gray-400">驱动:</span> <span x-text="data.database?.driver"></span></div>
                <div><span class="text-gray-400">延迟:</span> <span x-text="data.database?.latency_ms + 'ms'"></span></div>
                <div><span class="text-gray-400">日志总数:</span> <span x-text="data.database?.total_logs || '—'"></span></div>
            </div>
        </div>
    </div>

    <button @click="init()" class="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium">
        刷新状态
    </button>
</div>

<script>
function healthCheck() {
    return {
        data: {},
        async init() {
            const res = await fetch('/api/admin/health');
            this.data = await res.json();
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/health.html app/web/api.py
git commit -m "feat: add health check page and API"
```

---

### Task 10: Stats Page + API

**Files:**
- Create: `app/web/templates/stats.html`
- Modify: `app/web/api.py` — add stats endpoint

- [ ] **Step 1: Add stats API endpoint**

Append to `app/web/api.py`:

```python
@router.get("/stats")
async def stats_data(group_by: str = "day"):
    store = get_store()
    data = await store.get_stats(group_by)
    return data
```

- [ ] **Step 2: Create stats template**

`app/web/templates/stats.html`:

```html
{% extends "layout.html" %}
{% block content %}
<div x-data="statsPage()" x-init="init()">
    <div class="flex gap-3 mb-4">
        <button @click="groupBy = 'hour'; refresh()"
                :class="groupBy === 'hour' ? 'bg-blue-600' : 'bg-gray-700'"
                class="px-3 py-1.5 rounded text-sm">按小时</button>
        <button @click="groupBy = 'day'; refresh()"
                :class="groupBy === 'day' ? 'bg-blue-600' : 'bg-gray-700'"
                class="px-3 py-1.5 rounded text-sm">按天</button>
        <button @click="groupBy = 'model'; refresh()"
                :class="groupBy === 'model' ? 'bg-blue-600' : 'bg-gray-700'"
                class="px-3 py-1.5 rounded text-sm">按模型</button>
        <button @click="groupBy = 'path'; refresh()"
                :class="groupBy === 'path' ? 'bg-blue-600' : 'bg-gray-700'"
                class="px-3 py-1.5 rounded text-sm">按路径</button>
    </div>

    <div class="grid grid-cols-2 gap-4">
        <div class="bg-gray-800 rounded-lg p-4">
            <h4 class="text-sm text-gray-400 mb-2">请求量趋势</h4>
            <canvas id="chartRequests" height="250"></canvas>
        </div>
        <div class="bg-gray-800 rounded-lg p-4">
            <h4 class="text-sm text-gray-400 mb-2">Token 用量</h4>
            <canvas id="chartTokens" height="250"></canvas>
        </div>
    </div>

    <!-- Summary Table -->
    <div class="bg-gray-800 rounded-lg p-4 mt-4">
        <h4 class="text-sm text-gray-400 mb-3">详细数据</h4>
        <div class="overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-gray-400 border-b border-gray-700">
                        <th class="pb-2 text-left">时间段</th>
                        <th class="pb-2 text-right">请求数</th>
                        <th class="pb-2 text-right">成功数</th>
                        <th class="pb-2 text-right">成功率</th>
                        <th class="pb-2 text-right">Token</th>
                        <th class="pb-2 text-right">平均延迟</th>
                    </tr>
                </thead>
                <tbody>
                    <template x-for="r in data" :key="r.bucket">
                        <tr class="border-b border-gray-700/50">
                            <td class="py-2 font-mono text-xs" x-text="r.bucket"></td>
                            <td class="py-2 text-right font-mono" x-text="r.total"></td>
                            <td class="py-2 text-right font-mono" x-text="r.success"></td>
                            <td class="py-2 text-right font-mono" x-text="r.total > 0 ? Math.round(r.success/r.total*100)+'%' : '—'"></td>
                            <td class="py-2 text-right font-mono" x-text="r.tokens.toLocaleString()"></td>
                            <td class="py-2 text-right font-mono" x-text="Math.round(r.avg_ms) + 'ms'"></td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
function statsPage() {
    return {
        groupBy: 'day',
        data: [],
        chart1: null,
        chart2: null,
        async init() {
            await this.refresh();
        },
        async refresh() {
            const res = await fetch(`/api/admin/stats?group_by=${this.groupBy}`);
            this.data = (await res.json()).reverse();

            const labels = this.data.map(d => d.bucket);
            const totals = this.data.map(d => d.total);
            const tokens = this.data.map(d => d.tokens);

            if (this.chart1) this.chart1.destroy();
            if (this.chart2) this.chart2.destroy();

            this.chart1 = new Chart(document.getElementById('chartRequests'), {
                type: 'line',
                data: { labels, datasets: [{ label: '请求数', data: totals, borderColor: '#3b82f6', tension: 0.3 }] },
                options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#9ca3af' } }, y: { ticks: { color: '#9ca3af' } } } }
            });

            this.chart2 = new Chart(document.getElementById('chartTokens'), {
                type: 'bar',
                data: { labels, datasets: [{ label: 'Token', data: tokens, backgroundColor: '#10b981' }] },
                options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#9ca3af' } }, y: { ticks: { color: '#9ca3af' } } } }
            });
        }
    };
}
</script>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app/web/templates/stats.html app/web/api.py
git commit -m "feat: add statistics page with charts"
```

---

## Verification

After all tasks are complete:

```bash
# Restart service
# Then test each page
curl -s http://localhost:8000/admin | head -5          # redirect
curl -s http://localhost:8000/api/admin/dashboard | jq .  # dashboard data
curl -s http://localhost:8000/api/admin/health | jq .     # health data
curl -s http://localhost:8000/api/admin/logs | jq .       # log query

# Open browser: http://localhost:8000/admin
# Navigate through all 7 pages
# Test config save (write invalid YAML, verify error)
# Test live logs (send API request, watch it appear)
# Test API test page
# Test stats with different groupings
```

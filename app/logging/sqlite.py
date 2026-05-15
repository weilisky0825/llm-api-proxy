from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiosqlite

from app.logging.store import LogEntry, LogResponse, LogStore

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS api_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT NOT NULL UNIQUE,
    timestamp     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    client_ip     TEXT,
    request_path  TEXT NOT NULL,
    request_model TEXT,
    request_api   TEXT NOT NULL,
    request_body  TEXT,
    request_headers TEXT,
    status_code   INTEGER,
    response_body TEXT,
    response_time_ms INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    total_tokens  INTEGER
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON api_logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_request_api ON api_logs(request_api);",
    "CREATE INDEX IF NOT EXISTS idx_request_model ON api_logs(request_model);",
]

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

ALTER_API_LOGS_PROVIDER = [
    "ALTER TABLE api_logs ADD COLUMN provider_name TEXT DEFAULT '';",
    "ALTER TABLE api_logs ADD COLUMN upstream_url TEXT DEFAULT '';",
]

INSERT_REQUEST = """
INSERT INTO api_logs (request_id, client_ip, request_path, request_model, request_api, request_body, request_headers, user_id, user_name, provider_name, upstream_url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

UPDATE_RESPONSE = """
UPDATE api_logs SET status_code = ?, response_body = ?, response_time_ms = ?,
    input_tokens = ?, output_tokens = ?, total_tokens = ?
WHERE request_id = ?;
"""


class SQLiteStore(LogStore):
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(CREATE_TABLE)
            for idx in CREATE_INDEXES:
                await db.execute(idx)
            await db.commit()
        # Create new tables for user management
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(CREATE_ADMIN_USERS)
            await db.execute(CREATE_USERS)
            await db.execute(CREATE_ADMIN_SESSIONS)
            for stmt in ALTER_API_LOGS_USER:
                try:
                    await db.execute(stmt)
                except Exception:
                    pass  # column already exists
            for stmt in ALTER_API_LOGS_PROVIDER:
                try:
                    await db.execute(stmt)
                except Exception:
                    pass  # column already exists
            await db.commit()
        # Create default admin (password: admin123)
        import bcrypt
        default_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES ('admin', ?)",
                (default_hash,)
            )
            await db.commit()
        self._initialized = True
        asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            try:
                op, data = await self._queue.get()
                async with aiosqlite.connect(self._db_path) as db:
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
                                data.get("provider_name", ""),
                                data.get("upstream_url", ""),
                            ),
                        )
                    elif op == "response":
                        await db.execute(
                            UPDATE_RESPONSE,
                            (
                                data["status_code"],
                                data["response_body"],
                                data["response_time_ms"],
                                data["input_tokens"],
                                data["output_tokens"],
                                data["total_tokens"],
                                data["request_id"],
                            ),
                        )
                    await db.commit()
                self._queue.task_done()
            except Exception:
                logger.exception("Failed to write log to SQLite")

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
                    "provider_name": entry.provider_name,
                    "upstream_url": entry.upstream_url,
                },
            )
        )

    async def update_response(self, request_id: str, response: LogResponse) -> None:
        await self._ensure_initialized()
        await self._queue.put(
            (
                "response",
                {
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "response_body": response.response_body,
                    "response_time_ms": response.response_time_ms,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "total_tokens": response.total_tokens,
                },
            )
        )

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
            if filters.get("user_id"):
                conditions.append("user_id = ?")
                params.append(int(filters["user_id"]))

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

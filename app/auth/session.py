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
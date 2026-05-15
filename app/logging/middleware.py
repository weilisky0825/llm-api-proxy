from __future__ import annotations

import time
import uuid
from typing import Any

from app.config import settings
from app.logging.store import LogEntry, LogResponse, LogStore
from app.logging.sqlite import SQLiteStore


class LogMiddleware:
    def __init__(self, store: LogStore):
        self._store = store

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
            provider_name=request_data.get("provider_name", ""),
            upstream_url=request_data.get("upstream_url", ""),
        )
        await self._store.log_request(entry)
        return request_id

    async def on_response(
        self,
        request_id: str,
        status_code: int,
        response_body: str,
        response_time_ms: int,
        usage: dict[str, int] | None = None,
    ):
        resp = LogResponse(
            status_code=status_code,
            response_body=response_body,
            response_time_ms=response_time_ms,
            input_tokens=usage.get("input_tokens") if usage else None,
            output_tokens=usage.get("output_tokens") if usage else None,
            total_tokens=usage.get("total_tokens") if usage else None,
        )
        await self._store.update_response(request_id, resp)


def get_middleware() -> LogMiddleware:
    return LogMiddleware(store=SQLiteStore(settings.database.sqlite.path))

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


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
    provider_name: str = ""
    upstream_url: str = ""


@dataclass
class LogResponse:
    status_code: int = 0
    response_body: str = ""
    response_time_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LogStore(Protocol):
    async def log_request(self, entry: LogEntry) -> None: ...
    async def update_response(self, request_id: str, response: LogResponse) -> None: ...

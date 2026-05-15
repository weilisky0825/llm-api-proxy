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
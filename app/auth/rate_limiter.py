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
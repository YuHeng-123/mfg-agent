"""限流：按调用方计数，超阈值返回 429，而不是让它打到检索和模型上。

为什么要自己写：这里的限流是"保护单进程里那点 CPU"——检索一次几十毫秒、
真模型一次几秒。一个脚本循环调 `/api/ask` 就能把服务拖死，而这不是并发问题，
是**配额**问题。所以按调用方（API key，没有就按 IP）做滑动窗口。

两个窗口一起看：
  - 每分钟：防止突发打爆（一个脚本 at full speed 就是这种情况）
  - 每天：防止慢速刷穿（每秒 1 次持续一天，分钟窗口永远不超）

计数器在进程内存里，重启归零。单容器试点够用；多副本要换成 Redis，
这一点写在 docs/ops.md 里，不含糊过去。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

MINUTE = 60.0
DAY = 86400.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    window: str = "minute"

    def headers(self) -> dict[str, str]:
        h = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Window": self.window,
        }
        if not self.allowed:
            h["Retry-After"] = str(self.retry_after)
        return h


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int = 0) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self._lock = threading.Lock()
        self._minute: dict[str, deque[float]] = {}
        self._day: dict[str, deque[float]] = {}
        self.blocked_total = 0

    def reset(self) -> None:
        with self._lock:
            self._minute.clear()
            self._day.clear()
            self.blocked_total = 0

    @staticmethod
    def _prune(bucket: deque[float], now: float, window: float) -> None:
        while bucket and now - bucket[0] > window:
            bucket.popleft()

    def check(self, identity: str, now: float | None = None) -> Decision:
        now = time.time() if now is None else now
        with self._lock:
            minute = self._minute.setdefault(identity, deque())
            self._prune(minute, now, MINUTE)
            if len(minute) >= self.per_minute:
                self.blocked_total += 1
                wait = int(MINUTE - (now - minute[0])) + 1
                return Decision(False, self.per_minute, 0, wait, "minute")

            if self.per_day:
                day = self._day.setdefault(identity, deque())
                self._prune(day, now, DAY)
                if len(day) >= self.per_day:
                    self.blocked_total += 1
                    wait = int(DAY - (now - day[0])) + 1
                    return Decision(False, self.per_day, 0, wait, "day")

            minute.append(now)
            if self.per_day:
                self._day[identity].append(now)
            return Decision(True, self.per_minute, max(self.per_minute - len(minute), 0), 0)

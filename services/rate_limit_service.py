"""Rate limit em memória para o protótipo; cada processo mantém sua própria janela."""

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    def __init__(self):
        self._requests = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key, limit, window_seconds):
        now = monotonic()
        with self._lock:
            bucket = self._requests[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, 0

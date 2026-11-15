"""Sliding-window limit on build starts per client address."""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import deque
from collections.abc import Callable

MAX_CLIENTS = 50_000  # bound on remembered addresses; the oldest-idle are dropped first


def client_key(host: str) -> str:
    """The rate-limit identity of an address.

    IPv4-mapped IPv6 (::ffff:a.b.c.d) becomes the plain IPv4 address, other IPv6 collapses
    to its /64 (one subscriber holds a whole /64 and can rotate within it), and anything
    that is not an address is kept, truncated.
    """
    try:
        ip = ipaddress.ip_address(host.strip())
    except ValueError:
        return host.strip()[:64] or "unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class RateLimiter:
    """At most `limit` events per `window_s` seconds for each client."""

    def __init__(self, limit: int, window_s: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = {}
        self._seen: dict[str, float] = {}  # client -> last request time (for the count only)
        self._lock = threading.Lock()

    def _recent(self, client: str, now: float) -> deque[float]:
        hits = self._hits.get(client, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        return hits

    def try_acquire(self, client: str) -> int:
        """Check and reserve one start in a single step.

        Returns 0 when a start was reserved for `client`, else the seconds to wait.
        """
        with self._lock:
            now = self.clock()
            self._seen.pop(client, None)
            self._seen[client] = now
            if len(self._seen) > MAX_CLIENTS:
                del self._seen[next(iter(self._seen))]
            hits = self._recent(client, now)
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window_s - now))
            hits.append(now)
            self._hits[client] = hits
            if len(self._hits) > MAX_CLIENTS:
                self._prune(now)
            return 0

    def clients_seen(self) -> int:
        """How many distinct client keys asked within the current window (a count only)."""
        with self._lock:
            now = self.clock()
            return sum(t > now - self.window_s for t in self._seen.values())

    def refund(self, client: str) -> None:
        """Give back the most recent reservation (no build was started after all)."""
        with self._lock:
            hits = self._hits.get(client)
            if hits:
                hits.pop()

    def _prune(self, now: float) -> None:
        for c in [c for c, h in self._hits.items() if not h or h[-1] <= now - self.window_s]:
            del self._hits[c]
        while len(self._hits) > MAX_CLIENTS:
            del self._hits[next(iter(self._hits))]

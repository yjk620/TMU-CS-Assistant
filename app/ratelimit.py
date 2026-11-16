# per-client rate limit for /ask: at most LIMIT requests in any WINDOW-second span (sliding window)
# in memory, so it resets on restart and counts per process; enough for one small instance

import time
from collections import defaultdict, deque

LIMIT = 10
WINDOW = 60


class RateLimiter:
    def __init__(self, limit=LIMIT, window=WINDOW, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.hits = defaultdict(deque)

    #True if this client may make a request now (and counts it); False if it's over the limit
    def allow(self, client):
        now = self.clock()
        hits = self.hits[client]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


#the client's IP. Behind the host's proxy the socket address is the proxy's, so read X-Forwarded-For.
#Each proxy appends the address it received from, so the entry `proxy_hops` from the right is the one
#our own proxy saw; entries further left are written by the client and can be faked.
#proxy_hops = 0 means no proxy: use the socket address
def client_ip(forwarded_for, socket_ip, proxy_hops):
    if proxy_hops <= 0 or not forwarded_for:
        return socket_ip
    entries = [e.strip() for e in forwarded_for.split(",") if e.strip()]
    if not entries:
        return socket_ip
    return entries[-min(proxy_hops, len(entries))]

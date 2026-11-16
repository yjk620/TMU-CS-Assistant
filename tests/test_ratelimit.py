from app.ratelimit import RateLimiter, client_ip


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter(limit=3, window=60, clock=Clock())
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_clients_are_counted_separately():
    limiter = RateLimiter(limit=1, window=60, clock=Clock())
    assert limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("a")


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(limit=2, window=60, clock=clock)
    assert limiter.allow("a")
    clock.now = 30
    assert limiter.allow("a")
    assert not limiter.allow("a")
    clock.now = 60  # the first request is now 60 s old and drops out
    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_client_ip_without_proxy_uses_socket():
    assert client_ip("1.2.3.4", "9.9.9.9", 0) == "9.9.9.9"


def test_client_ip_takes_the_entry_our_proxy_added():
    # the client faked "6.6.6.6"; the proxy appended the real address
    assert client_ip("6.6.6.6, 1.2.3.4", "10.0.0.1", 1) == "1.2.3.4"
    assert client_ip("6.6.6.6, 1.2.3.4, 10.0.0.2", "10.0.0.1", 2) == "1.2.3.4"


def test_client_ip_missing_header_falls_back_to_socket():
    assert client_ip(None, "9.9.9.9", 1) == "9.9.9.9"
    assert client_ip(" , ", "9.9.9.9", 1) == "9.9.9.9"

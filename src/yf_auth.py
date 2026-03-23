"""Centralized yfinance authentication & session manager.

Provides:
- A shared curl_cffi session (required by yfinance >= 1.0)
- Thread-safe rate limiting to avoid Yahoo Finance 401/429 errors
- Coordinated crumb refresh on auth failures
"""
import threading
import time

# ── Shared session ────────────────────────────────────────────────────────────
# yfinance 1.x requires curl_cffi, not plain requests.Session.
# We do NOT pass a custom session — instead we let yfinance manage its own
# curl_cffi session internally, but we control concurrency & crumb refresh.

_session_lock = threading.Lock()


def get_session():
    """Return None — yfinance 1.x manages its own curl_cffi session.

    Callers should use `yf.Ticker(ticker)` (no session arg).
    This function exists for API compatibility with modules that imported it.
    """
    return None


# ── Rate limiter ──────────────────────────────────────────────────────────────
# Limits concurrent yfinance requests to avoid curl_cffi DNS thread exhaustion.
# curl_cffi spawns a getaddrinfo thread per connection, so we cap at 5 to stay
# well within system thread limits.  No global interval needed — the semaphore
# naturally throttles throughput (~5 req/s).

_rate_semaphore = threading.Semaphore(5)  # max 5 concurrent requests


def rate_limit():
    """Call before each yfinance request to throttle."""
    _rate_semaphore.acquire()


def rate_release():
    """Call after each yfinance request completes."""
    _rate_semaphore.release()


# ── Crumb management ─────────────────────────────────────────────────────────

_crumb_generation = 0
_crumb_lock = threading.Lock()


def warmup(max_attempts=3):
    """Pre-fetch crumb/cookie before parallel work. Retries on failure."""
    global _crumb_generation
    for attempt in range(max_attempts):
        try:
            from yfinance.data import YfData
            yd = YfData()
            yd._get_cookie_and_crumb()
            with _crumb_lock:
                _crumb_generation += 1
            return True
        except Exception:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
    return False


def refresh_crumb():
    """Periodic crumb refresh — call every N tickers from the main loop."""
    try:
        from yfinance.data import YfData
        yd = YfData()
        yd._get_cookie_and_crumb()
    except Exception:
        pass


def on_auth_error(seen_generation):
    """Called by a worker thread after a 401 error.

    Returns the new generation number. Only one thread actually
    performs the refresh; others wait and reuse the result.
    """
    global _crumb_generation
    with _crumb_lock:
        if _crumb_generation != seen_generation:
            return _crumb_generation
        # We're the first thread to see this stale crumb — evict and refresh
        try:
            from yfinance.data import YfData
            yd = YfData()
            with yd._cookie_lock:
                yd._crumb = None
                yd._cookie = None
                yd._cookie_strategy = 'basic'
        except Exception:
            pass
        time.sleep(1)  # brief pause before refreshing
        try:
            from yfinance.data import YfData
            YfData()._get_cookie_and_crumb()
        except Exception:
            pass
        _crumb_generation += 1
        return _crumb_generation


def get_generation():
    """Get current crumb generation (for passing to on_auth_error)."""
    return _crumb_generation


def is_auth_error(exc):
    """Check if an exception is a crumb/auth error."""
    err = str(exc).lower()
    return "401" in err or "crumb" in err or "unauthorized" in err

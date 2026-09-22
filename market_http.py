"""Reusable buffered GET connections; sessions are leased to one caller at a time.

No response cache, added retries or credentials. Existing caller backoff owns
429/5xx behavior. Idle sessions are bounded, including during concurrent scans.
"""
from queue import LifoQueue, Empty, Full
import threading
import requests


class MarketHttp:
    def __init__(self, max_idle=16, session_factory=None):
        self._idle = LifoQueue(maxsize=max_idle)
        self._factory = session_factory or requests.Session
        self._lock = threading.Lock()
        self._requests = self._created = self._reused = 0

    def get(self, url, **kwargs):
        if kwargs.get("stream"):
            raise ValueError("market_http_requires_buffered_response")
        try:
            session = self._idle.get_nowait()
            reused = True
        except Empty:
            session = self._factory()
            reused = False
        with self._lock:
            self._requests += 1
            self._created += not reused
            self._reused += reused
        try:
            response = session.get(url, **kwargs)
        except BaseException:
            session.close()
            raise
        # Requests buffers GET bodies by default, so the connection is ready
        # before we return the response or lease this session to another worker.
        session.cookies.clear()
        try:
            self._idle.put_nowait(session)
        except Full:
            session.close()
        return response

    def snapshot(self):
        with self._lock:
            return {"requests":self._requests, "sessions_created":self._created,
                    "session_reuses":self._reused, "idle_sessions":self._idle.qsize()}

    def close(self):
        while True:
            try:
                self._idle.get_nowait().close()
            except Empty:
                return

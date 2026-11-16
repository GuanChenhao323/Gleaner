import asyncio
import time

import httpx

from gleaner.monitoring.models import Clock


class FakeClock(Clock):
    def __init__(self, start=None):
        self.now = time.time() if start is None else start
        self.elapsed = 1000.0

    def utc(self):
        return self.now

    def mono(self):
        return self.elapsed

    def advance(self, seconds):
        self.now += seconds
        self.elapsed += seconds

    async def sleep(self, seconds):
        self.advance(max(0, seconds))
        await asyncio.sleep(0)


class Stream(httpx.AsyncByteStream):
    def __init__(self, body=b"ok", delay=0):
        self.body, self.delay, self.closed = body, delay, False

    async def __aiter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        for offset in range(0, len(self.body), 100):
            yield self.body[offset : offset + 100]

    async def aclose(self):
        self.closed = True


def cookie(value="SYNTHETIC_SECRET", **overrides):
    return {
        "name": "MoodleSession",
        "value": value,
        "domain": "moodle.must.edu.mo",
        "path": "/",
        "host_only": True,
        "secure": True,
        "http_only": True,
        "same_site": "lax",
        "session": True,
        "expires_at": None,
        **overrides,
    }

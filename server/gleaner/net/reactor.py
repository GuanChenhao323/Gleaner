"""手写反应器（Reactor）：基于 ``selectors`` 的单线程事件循环，可选 epoll / poll / select。

用于推送节点的 WebSocket 接入层，也是对比实验 1（select 与 epoll）的被测对象：

- I/O 多路复用：``EpollSelector``（Linux，O(就绪数)）或 ``SelectSelector``（O(连接数)，受 FD_SETSIZE=1024 限制）
- 跨线程调用：其他线程用 ``call_soon_threadsafe`` 投递回调，并写一个字节到 socketpair 唤醒 ``select()``
- 定时器：最小堆
"""

from __future__ import annotations

import heapq
import itertools
import logging
import selectors
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

IOCallback = Callable[[Any, int], None]  # (fileobj, mask)


def make_selector(kind: str = "auto") -> selectors.BaseSelector:
    if kind == "epoll" and hasattr(selectors, "EpollSelector"):
        return selectors.EpollSelector()
    if kind == "poll" and hasattr(selectors, "PollSelector"):
        return selectors.PollSelector()
    if kind == "select":
        return selectors.SelectSelector()
    return selectors.DefaultSelector()  # Linux 上即 epoll


class Reactor:
    def __init__(self, kind: str = "auto") -> None:
        self.selector = make_selector(kind)
        self.kind = type(self.selector).__name__
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        self.selector.register(self._wake_r, selectors.EVENT_READ, self._on_wake)
        self._calls: deque[Callable[[], None]] = deque()
        self._timers: list[tuple[float, int, Callable[[], None]]] = []
        self._seq = itertools.count()
        self._running = False
        self._thread: threading.Thread | None = None
        self.loop_iterations = 0

    # -- 注册 --------------------------------------------------------------------

    def register(self, sock: socket.socket, events: int, cb: IOCallback) -> None:
        self.selector.register(sock, events, cb)

    def modify(self, sock: socket.socket, events: int, cb: IOCallback) -> None:
        self.selector.modify(sock, events, cb)

    def unregister(self, sock: socket.socket) -> None:
        try:
            self.selector.unregister(sock)
        except (KeyError, ValueError):
            pass

    # -- 回调与定时器 --------------------------------------------------------------

    def call_soon_threadsafe(self, fn: Callable[[], None]) -> None:
        self._calls.append(fn)  # deque.append 是线程安全的
        try:
            self._wake_w.send(b"\0")
        except (BlockingIOError, OSError):
            pass  # 唤醒缓冲已满，说明 select 已经会醒来

    def call_later(self, delay: float, fn: Callable[[], None]) -> None:
        heapq.heappush(self._timers, (time.monotonic() + delay, next(self._seq), fn))

    def _on_wake(self, sock: Any, mask: int) -> None:
        try:
            while self._wake_r.recv(4096):
                pass
        except (BlockingIOError, OSError):
            pass

    # -- 主循环 ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        while self._running:
            timeout: float | None = None
            if self._calls:
                timeout = 0
            elif self._timers:
                timeout = max(0.0, self._timers[0][0] - time.monotonic())
            for key, mask in self.selector.select(timeout):
                try:
                    key.data(key.fileobj, mask)
                except Exception:
                    log.exception("reactor io callback failed")
            now = time.monotonic()
            while self._timers and self._timers[0][0] <= now:
                _, _, fn = heapq.heappop(self._timers)
                self._safe(fn)
            for _ in range(len(self._calls)):
                self._safe(self._calls.popleft())
            self.loop_iterations += 1
        self.selector.close()
        self._wake_r.close()
        self._wake_w.close()

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("reactor callback failed")

    def start_thread(self, name: str = "reactor") -> None:
        self._thread = threading.Thread(target=self.run, name=name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        def _stop() -> None:
            self._running = False

        self.call_soon_threadsafe(_stop)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

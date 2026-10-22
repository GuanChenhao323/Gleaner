"""手写 Prometheus 文本格式（exposition format 0.0.4）指标。"""

from __future__ import annotations

import bisect
import math
import threading
from collections.abc import Callable

_LOCK = threading.Lock()

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _labels(names: tuple[str, ...], values: tuple[str, ...], extra: str = "") -> str:
    parts = [f'{n}="{_esc(v)}"' for n, v in zip(names, values, strict=True)]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt(v: float) -> str:
    if math.isinf(v):
        return "+Inf" if v > 0 else "-Inf"
    return repr(float(v)) if not float(v).is_integer() else str(int(v))


class _Metric:
    type = "untyped"

    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help
        self.labelnames = labels

    def header(self) -> list[str]:
        return [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.type}"]


class Counter(_Metric):
    type = "counter"

    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()) -> None:
        super().__init__(name, help, labels)
        self._v: dict[tuple[str, ...], float] = {}

    def inc(self, n: float = 1.0, *labels: str) -> None:
        with _LOCK:
            self._v[labels] = self._v.get(labels, 0.0) + n

    def render(self) -> list[str]:
        out = self.header()
        for k, v in sorted(self._v.items()):
            out.append(f"{self.name}{_labels(self.labelnames, k)} {_fmt(v)}")
        return out


class Gauge(_Metric):
    type = "gauge"

    def __init__(
        self,
        name: str,
        help: str,
        labels: tuple[str, ...] = (),
        fn: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(name, help, labels)
        self._v: dict[tuple[str, ...], float] = {}
        self.fn = fn

    def set(self, v: float, *labels: str) -> None:
        self._v[labels] = v

    def inc(self, n: float = 1.0, *labels: str) -> None:
        self._v[labels] = self._v.get(labels, 0.0) + n

    def render(self) -> list[str]:
        out = self.header()
        if self.fn is not None:
            out.append(f"{self.name} {_fmt(self.fn())}")
        for k, v in sorted(self._v.items()):
            out.append(f"{self.name}{_labels(self.labelnames, k)} {_fmt(v)}")
        return out


class Histogram(_Metric):
    type = "histogram"

    def __init__(
        self,
        name: str,
        help: str,
        labels: tuple[str, ...] = (),
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, help, labels)
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sum: dict[tuple[str, ...], float] = {}

    def observe(self, v: float, *labels: str) -> None:
        with _LOCK:
            c = self._counts.setdefault(labels, [0] * (len(self.buckets) + 1))
            c[bisect.bisect_left(self.buckets, v)] += 1
            self._sum[labels] = self._sum.get(labels, 0.0) + v

    def render(self) -> list[str]:
        out = self.header()
        for k, counts in sorted(self._counts.items()):
            acc = 0
            for b, n in zip((*self.buckets, math.inf), counts, strict=True):
                acc += n
                out.append(
                    f"{self.name}_bucket{_labels(self.labelnames, k, f'le="{_fmt(b)}"')} {acc}"
                )
            out.append(f"{self.name}_sum{_labels(self.labelnames, k)} {_fmt(self._sum[k])}")
            out.append(f"{self.name}_count{_labels(self.labelnames, k)} {acc}")
        return out


class Registry:
    def __init__(self) -> None:
        self.metrics: list[_Metric] = []

    def counter(self, name: str, help: str, labels: tuple[str, ...] = ()) -> Counter:
        m = Counter(name, help, labels)
        self.metrics.append(m)
        return m

    def gauge(
        self,
        name: str,
        help: str,
        labels: tuple[str, ...] = (),
        fn: Callable[[], float] | None = None,
    ) -> Gauge:
        m = Gauge(name, help, labels, fn)
        self.metrics.append(m)
        return m

    def histogram(
        self,
        name: str,
        help: str,
        labels: tuple[str, ...] = (),
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        m = Histogram(name, help, labels, buckets)
        self.metrics.append(m)
        return m

    def render(self) -> str:
        lines: list[str] = []
        for m in self.metrics:
            lines += m.render()  # type: ignore[attr-defined]
        return "\n".join(lines) + "\n"


REGISTRY = Registry()


def metrics_handler(registry: Registry = REGISTRY) -> Callable[..., object]:
    from ..net.http import Response

    async def handler(req: object) -> Response:
        return Response.text_body(
            registry.render(), content_type="text/plain; version=0.0.4; charset=utf-8"
        )

    return handler

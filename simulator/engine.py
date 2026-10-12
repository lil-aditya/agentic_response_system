from __future__ import annotations
import random
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import Deployment, IncidentSpec, LogLine, MetricPoint

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

DEPENDENCIES = {
    "gateway": ["orders"],
    "orders": ["db", "worker"],
    "worker": ["db"],
    "db": [],
}

# (mean, noise std)
BASELINES = {
    "gateway": {"error_rate": (0.005, 0.002), "latency_p95_ms": (120, 15),
                "cpu_pct": (30, 4), "memory_mb": (512, 10)},
    "orders": {"error_rate": (0.004, 0.002), "latency_p95_ms": (90, 12),
               "cpu_pct": (35, 4), "memory_mb": (768, 12)},
    "db": {"error_rate": (0.001, 0.0005), "latency_p95_ms": (15, 3),
           "cpu_pct": (25, 3), "memory_mb": (2048, 20),
           "connections_active": (30, 4), "connections_max": (100, 0)},
    "worker": {"error_rate": (0.002, 0.001), "latency_p95_ms": (200, 25),
               "cpu_pct": (20, 3), "memory_mb": (400, 8), "queue_depth": (20, 5)},
}


def _rng(seed: int, *parts: str) -> random.Random:
    return random.Random(seed ^ zlib.crc32("|".join(parts).encode()))


class Simulation:
    def __init__(self, spec: IncidentSpec):
        self.spec = spec
        self._metrics: dict[tuple[str, str], list[float]] = {}
        self._logs: list[LogLine] = []
        self._build()

    @classmethod
    def from_file(cls, path: str | Path) -> "Simulation":
        return cls(IncidentSpec(**yaml.safe_load(Path(path).read_text())))

    # ---- time helpers ----
    def ts(self, minute: int, second: int = 0) -> datetime:
        return T0 + timedelta(minutes=minute, seconds=second)

    @property
    def now(self) -> datetime:
        return self.ts(self.spec.duration_minutes)

    def _minute(self, t: datetime) -> int:
        return int((t - T0).total_seconds() // 60)

    # ---- generation ----
    def _build(self) -> None:
        n = self.spec.duration_minutes
        for svc, metrics in BASELINES.items():
            for name, (mean, std) in metrics.items():
                rng = _rng(self.spec.seed, svc, name)
                series = [max(0.0, rng.gauss(mean, std)) for _ in range(n)]
                for e in self.spec.effects:
                    if e.service != svc or e.metric != name:
                        continue
                    for m in range(e.start, n):
                        if e.shape == "step" or e.end is None or m >= e.end:
                            p = 1.0
                        else:
                            p = (m - e.start) / max(1, e.end - e.start)
                        series[m] = series[m] + (e.to - series[m]) * p
                self._metrics[(svc, name)] = series

        for svc in BASELINES:
            rng = _rng(self.spec.seed, svc, "baseline-logs")
            for m in range(n):
                self._logs.append(LogLine(ts=self.ts(m, rng.randint(0, 59)),
                                          service=svc, level="INFO",
                                          message="request handled ok"))
        for i, r in enumerate(self.spec.logs):
            rng = _rng(self.spec.seed, r.service, "rule", str(i))
            for m in range(r.start, r.end or n):
                count = max(0, round(rng.gauss(r.rate, r.rate * 0.2)))
                for _ in range(count):
                    self._logs.append(LogLine(ts=self.ts(m, rng.randint(0, 59)),
                                              service=r.service, level=r.level,
                                              message=r.message))
        self._logs.sort(key=lambda l: (l.ts, l.service))

    # ---- query surface (what tools will wrap) ----
    def list_services(self) -> list[str]:
        return list(BASELINES)

    def get_dependencies(self) -> dict[str, list[str]]:
        return DEPENDENCIES

    def list_metrics(self, service: str) -> list[str]:
        return list(BASELINES[service])

    def get_metrics(self, service: str, metric: str,
                    start: datetime, end: datetime) -> list[MetricPoint]:
        series = self._metrics[(service, metric)]
        lo, hi = max(0, self._minute(start)), min(len(series), self._minute(end))
        return [MetricPoint(ts=self.ts(m), value=round(series[m], 4))
                for m in range(lo, hi)]

    def get_logs(self, start: datetime, end: datetime, service: str | None = None,
                 level: str | None = None, limit: int = 100, cursor: int = 0) -> dict:
        rows = [l for l in self._logs
                if start <= l.ts < end
                and (service is None or l.service == service)
                and (level is None or l.level == level)]
        page = rows[cursor:cursor + limit]
        nxt = cursor + limit if cursor + limit < len(rows) else None
        return {"lines": page, "next_cursor": nxt, "total": len(rows)}

    def get_deployments(self, start: datetime, end: datetime) -> list[Deployment]:
        return [d for d in self.spec.deployments
                if start <= self.ts(d.minute) < end]

    def get_health(self, service: str, at: datetime) -> str:
        m = min(max(self._minute(at), 0), self.spec.duration_minutes - 1)
        err = self._metrics[(service, "error_rate")][m]
        lat = self._metrics[(service, "latency_p95_ms")][m]
        return "unhealthy" if err > 0.05 or lat > 1000 else "healthy"
"""Performance regression test for /api/admin/overview/metrics.

Guards against schema regression where someone re-introduces 30+ serial queries.
On local SQLite with empty-ish DB this endpoint should respond in < 200ms.
Not a SM-4 benchmark (that requires staging + PostgreSQL + k6/locust);
this is a regression guard only.
"""
import statistics
import time
import pytest


@pytest.mark.asyncio
async def test_overview_metrics_perf_regression(async_client, admin_headers):
    # Warm up once (DB connection, scheduler init, etc.)
    r0 = await async_client.get("/api/admin/overview/metrics", headers=admin_headers)
    assert r0.status_code == 200

    # Measure 20 calls
    durations = []
    for _ in range(20):
        start = time.perf_counter()
        r = await async_client.get("/api/admin/overview/metrics", headers=admin_headers)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        durations.append(elapsed_ms)

    mean_ms = statistics.mean(durations)
    p95_ms = statistics.quantiles(durations, n=20)[-1]  # 95th percentile

    print(f"overview/metrics: mean={mean_ms:.1f}ms, p95={p95_ms:.1f}ms over 20 calls")

    # SQLite local bounds — intentionally loose for CI stability.
    # Real SM-4 (p95 < 500ms on PostgreSQL) requires staging benchmark.
    assert mean_ms < 300, f"mean response time {mean_ms:.1f}ms exceeded 300ms threshold"
    assert p95_ms < 500, f"p95 response time {p95_ms:.1f}ms exceeded 500ms threshold"

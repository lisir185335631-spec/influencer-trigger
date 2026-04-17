"""
Admin Diagnostics API — health checks for DB, Redis, WebSocket, Scheduler, System.
"""
import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.admin.deps import require_admin
from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.scheduler import scheduler
from app.schemas.auth import TokenData
from app.websocket.manager import manager

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnostics", tags=["admin-diagnostics"])

settings = get_settings()


# ─── Internal check helpers (no Depends, safe to call directly) ───────────────

async def _check_db() -> dict:
    from sqlalchemy import text
    start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    pool = engine.pool
    try:
        pool_size = pool.size() if callable(getattr(pool, "size", None)) else None
        checked_out = pool.checkedout() if callable(getattr(pool, "checkedout", None)) else None
        overflow = pool.overflow() if callable(getattr(pool, "overflow", None)) else None
    except Exception:
        pool_size = checked_out = overflow = None

    return {
        "status": "ok",
        "latency_ms": latency_ms,
        "pool": {
            "size": pool_size,
            "checked_out": checked_out,
            "overflow": overflow,
        },
        "slow_queries_top10": [],
    }


async def _check_redis() -> dict:
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        start = time.perf_counter()
        await client.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        info = await client.info()
        key_count = await client.dbsize()
        queue_depth = (
            await client.llen("task_queue")
            if await client.exists("task_queue")
            else 0
        )
        await client.aclose()
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "connected_clients": info.get("connected_clients", 0),
            "used_memory_human": info.get("used_memory_human", "unknown"),
            "key_count": key_count,
            "queue_depth": queue_depth,
        }
    except Exception as e:
        return {"status": "not_configured", "reason": str(e)}


async def _check_websocket() -> dict:
    total = len(manager.active_connections)
    return {
        "status": "ok",
        "active_connections": total,
        "channels": {"default": total},
    }


async def _check_scheduler() -> dict:
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": next_run,
            "trigger": str(job.trigger),
        })
    return {
        "status": "ok",
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": jobs,
    }


async def _check_system() -> dict:
    if not _PSUTIL_AVAILABLE:
        return {"status": "not_available", "reason": "psutil not installed"}

    import os

    try:
        disk = psutil.disk_usage(".")
        mem = psutil.virtual_memory()
        proc = psutil.Process(os.getpid())
        proc_info = proc.as_dict(
            attrs=["pid", "name", "cpu_percent", "memory_info", "create_time", "num_threads"]
        )
        mem_info = proc_info.get("memory_info")
        create_time = proc_info.get("create_time")
        return {
            "status": "ok",
            "disk": {
                "total_gb": round(disk.total / 1e9, 2),
                "used_gb": round(disk.used / 1e9, 2),
                "free_gb": round(disk.free / 1e9, 2),
                "percent": disk.percent,
            },
            "memory": {
                "total_gb": round(mem.total / 1e9, 2),
                "used_gb": round(mem.used / 1e9, 2),
                "available_gb": round(mem.available / 1e9, 2),
                "percent": mem.percent,
            },
            "process": {
                "pid": proc_info.get("pid"),
                "name": proc_info.get("name"),
                "cpu_percent": proc_info.get("cpu_percent"),
                "memory_rss_mb": round(mem_info.rss / 1e6, 2) if mem_info else None,
                "num_threads": proc_info.get("num_threads"),
                "uptime_s": round(time.time() - create_time) if create_time else None,
            },
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ─── Public Endpoints ─────────────────────────────────────────────────────────

@router.get("/db")
async def get_db_health(_: TokenData = Depends(require_admin)) -> dict:
    return await _check_db()


@router.get("/redis")
async def get_redis_health(_: TokenData = Depends(require_admin)) -> dict:
    return await _check_redis()


@router.get("/websocket")
async def get_ws_health(_: TokenData = Depends(require_admin)) -> dict:
    return await _check_websocket()


@router.get("/scheduler")
async def get_scheduler_health(_: TokenData = Depends(require_admin)) -> dict:
    return await _check_scheduler()


@router.get("/system")
async def get_system_health(_: TokenData = Depends(require_admin)) -> dict:
    return await _check_system()


@router.post("/healthcheck")
async def full_healthcheck(_: TokenData = Depends(require_admin)) -> dict:
    results_raw = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_websocket(),
        _check_scheduler(),
        _check_system(),
        return_exceptions=True,
    )

    names = ["db", "redis", "websocket", "scheduler", "system"]
    components: dict = {}
    overall = "ok"

    for name, res in zip(names, results_raw):
        if isinstance(res, Exception):
            components[name] = {"status": "error", "reason": str(res)}
            overall = "error"
        else:
            components[name] = res
            s = res.get("status", "error")
            if s == "error" and overall != "error":
                overall = "error"
            elif s not in ("ok", "not_configured", "not_available") and overall == "ok":
                overall = "degraded"

    return {
        "overall": overall,
        "checked_at": datetime.utcnow().isoformat(),
        "components": components,
    }

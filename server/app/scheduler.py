"""
Shared APScheduler singleton — imported by main.py and API routes.
Avoids circular imports when API routes need to reschedule jobs.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

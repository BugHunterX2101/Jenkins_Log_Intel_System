"""
One-shot script: wipe all simulated/test pipeline data from the database.
Keeps workers (config) and schema intact. Safe to run multiple times.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

from app.config import settings


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # Delete in FK-safe order
        r1 = await conn.execute(text("DELETE FROM stage_executions"))
        r2 = await conn.execute(text("DELETE FROM worker_assignments"))
        r3 = await conn.execute(text("DELETE FROM pipeline_runs"))
        r4 = await conn.execute(text("DELETE FROM build_events"))
        r5 = await conn.execute(text("DELETE FROM system_metrics"))

        # Reset workers load/status so they show IDLE with 0 load
        await conn.execute(text(
            "UPDATE workers SET status='IDLE', load=0.0, current_job=NULL, jobs_run=0"
        ))

    await engine.dispose()

    print(f"Deleted {r1.rowcount} stage_executions")
    print(f"Deleted {r2.rowcount} worker_assignments")
    print(f"Deleted {r3.rowcount} pipeline_runs")
    print(f"Deleted {r4.rowcount} build_events")
    print(f"Deleted {r5.rowcount} system_metrics")
    print("Workers reset to IDLE / 0 load")
    print("Done — database is clean.")


if __name__ == "__main__":
    asyncio.run(main())

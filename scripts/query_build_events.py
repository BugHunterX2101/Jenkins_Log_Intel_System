import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models import BuildEvent
from app.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        result = await session.execute(select(BuildEvent).order_by(BuildEvent.id.desc()).limit(5))
        rows = result.scalars().all()
        if not rows:
            print("No BuildEvent records found.")
            return
        for ev in rows:
            print(f"ID: {ev.id} | job: {ev.job_name}#{ev.build_number} | type: {ev.failure_type} | severity: {ev.severity} | delivery: {ev.delivery_status} | processed_at: {ev.processed_at}")

if __name__ == '__main__':
    asyncio.run(main())

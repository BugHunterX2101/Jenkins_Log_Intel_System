"""Delete fake sample-repo test data from database."""
import asyncio
from app.db import get_session_factory
from app.pipeline_models import PipelineRun
from sqlalchemy import delete

async def main():
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = delete(PipelineRun).where(
            PipelineRun.repo_url == 'https://github.com/test/sample-repo.git'
        )
        result = await session.execute(stmt)
        deleted = result.rowcount
        await session.commit()
        print(f'✓ Deleted {deleted} runs from fake sample-repo')
        print('✓ Database now contains only real repositories')

if __name__ == "__main__":
    asyncio.run(main())

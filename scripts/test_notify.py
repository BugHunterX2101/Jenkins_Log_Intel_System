import asyncio
from app.services import notifier
from app.config import settings

async def main():
    res = await notifier.notify(
        job_name="test-job",
        build_number=123,
        summary_text="This is a test summary from notifier",
        fix_suggestions=["restart service","check config"],
        severity="P2",
        log_url="http://localhost:8080/job/test/123/",
        email_to="dev@example.com",
        slack_channel=settings.SLACK_DEFAULT_CHANNEL,
    )
    print(res)

if __name__ == '__main__':
    asyncio.run(main())

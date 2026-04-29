Playwright smoke tests

Prerequisites:
- Node 18+ and npm
- (Optional) a running server at http://127.0.0.1:8000. If not running, tests will load `file://` pages.

Install and run:

```bash
npm install
npm run test:smoke
```

What the test does:
- Opens each main page (index, queue, webhooks, workers, simulation, scheduler, backend)
- Verifies top/side nav links have non-"#" hrefs
- Verifies key interactive elements exist (tables, action buttons)
- Captures screenshots into `frontend/smoke/screenshots/` for manual review

Notes:
- Tests use Playwright Test. If you prefer Python Playwright I can add that instead.
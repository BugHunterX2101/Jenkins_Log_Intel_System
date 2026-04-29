const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './frontend/smoke',
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});

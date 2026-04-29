# Frontend (Design-based static site)

This folder contains static HTML pages created from the `design/` directory to serve a simple frontend for the Jenkins Log Intel project.

Included pages:

- `index.html` — landing and links to other design pages
- `backend.html` — backend console (design copy)
- `queue.html` — job queue & DB viewer (design copy)
- `scheduler.html` — pipeline manager / scheduler (design copy)
- `webhooks.html` — webhook control panel (design copy)
- `simulation.html` — simulation control panel (design copy)
- `workers.html` — worker fleet monitor (design copy)

How to serve locally

Python (3.x) simple server from the workspace root:

```powershell
cd d:\Jenkins_Log_Intel_System\frontend
python -m http.server 8000
```

Then open http://localhost:8000 in your browser.

Notes
- These are static copies of the design pages. If you want a richer dev experience (live reload, single-page app), I can scaffold a React/Vite app and integrate these designs.
- The original full-design HTML is available under `design/` if you want to copy more exact markup or assets.

Localize assets (optional, recommended for offline use)

1. Build a local Tailwind CSS bundle and place it at `frontend/assets/styles.css`.

```powershell
cd d:\Jenkins_Log_Intel_System\frontend
npm init -y
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
# create ./src/input.css with your Tailwind directives (e.g. @tailwind base; @tailwind components; @tailwind utilities;)
npx tailwindcss -i ./src/input.css -o ./assets/styles.css --minify
```

2. Download the `Inter` font and Material Symbols, place the font files under `frontend/assets/fonts/`, and update `frontend/assets/fonts.css` with proper `@font-face` rules (placeholders are already in the file).

3. After building, serve the folder and the pages will use the local `assets/styles.css` and `assets/fonts.css` files as fallbacks (they are referenced in each HTML page). If you prefer I can automate the above and commit a built bundle for you.

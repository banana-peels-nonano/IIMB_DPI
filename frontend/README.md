# Mirror frontend

React + TypeScript + Vite app using the UX4G Web Components package.

## Local run

Requires Node.js 20.19+ and pnpm.

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

Open the address printed by Vite. The sample UI runs without the Python backend. When Flask is running on `http://127.0.0.1:8080`, the dev server can proxy `/_mirror_backend/health` to the existing `/health` route. Set `VITE_MIRROR_BACKEND_ORIGIN` in a local, untracked `.env` file in this folder to override the target origin.

The frontend currently has no endpoint for loading Mirror state or saving answers. Its sample screens and interactions are explicitly local demo behavior; live data and AA consent remain future integrations.

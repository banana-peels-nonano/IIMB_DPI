# Mirror frontend

React + TypeScript + Vite app using the UX4G Web Components package. The dependency manager is pinned to pnpm 11.25.0; Node.js 20.19 or newer is required.

## Local run

Requires Node.js 20.19+ and pnpm.

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

Open the address printed by Vite. The sample UI runs without the Python backend. When Flask is running on `http://127.0.0.1:8080`, the dev server can proxy `/_mirror_backend/health` to the existing `/health` route. Set `VITE_MIRROR_BACKEND_ORIGIN` in a local, untracked `.env` file in this folder to override the target origin.

The frontend currently has no endpoint for loading Mirror state or saving answers. Its sample screens and interactions are explicitly local demo behavior; live data and AA consent remain future integrations. The service indicator calls only `GET /health` through the Vite proxy and keeps only the response's boolean `ok`; it does not request `/captures`. The read-only `activeDemoSource` supplies the synthetic screens. `MirrorContractSource` describes the future customer API, while `DisabledLiveContractSource` fails closed because Flask currently exposes no customer contract or action routes. No backend files are changed by this frontend.

## Production container

Build a static frontend image with the included multi-stage `Dockerfile`:

```powershell
docker build -t mirror-frontend ./frontend
docker run --rm -p 4173:8080 -e MIRROR_BACKEND_ORIGIN=http://host.docker.internal:8080 mirror-frontend
```

Open `http://127.0.0.1:4173`. Nginx serves the static build, compresses CSS and JavaScript, applies baseline browser security headers, and falls back to `index.html` for client-side routes. `MIRROR_BACKEND_ORIGIN` must be the reachable backend origin only (scheme, host, and optional port). In hosted environments, route `/_mirror_backend/` to the private backend over the platform network; do not expose backend secrets to Vite or the browser. The container only proxies the current health request; adding customer API routes is a prerequisite for live household data, authentication, consent, and persisted actions.

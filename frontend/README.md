# Mirror frontend

React + TypeScript + Vite using the pinned UX4G Web Components package. Node.js 20.19+ and pnpm 11.25.0 are required.

## Local run

From the repository root, install the existing backend requirements once, then run the backend and frontend in separate terminals:

```powershell
Set-Location aa-kit
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe webhook_server.py
```

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the URL printed by Vite. The frontend proxies `/_mirror_backend/` to Flask at `http://127.0.0.1:8080`; set `VITE_MIRROR_BACKEND_ORIGIN` in an untracked `frontend/.env` file to select another local origin.

The customer API is a single-machine synthetic demo. On its first request it generates AA-shaped sample data under the operating system's local application-state directory and stores Mirror state there, outside this repository. It uses the existing deterministic engine, `build_payload()` and `validate_payload()`. Its loopback-only endpoints are:

- `GET /api/customer/session` and `GET /api/customer/contract`
- `POST /api/customer/answers`
- `POST /api/customer/facts/correct`
- `POST /api/customer/purpose`
- `POST /api/customer/forget`

It does not read `captures/`, credentials, or real account data. It has no login, AA connection, or live consent journey. Do not expose this unauthenticated demo API to a network or use it with real household data. Live AA integration needs a separately designed authenticated customer session and verified consent/household correlation. The existing `/health`, `/captures`, and `/aa/*` webhook behavior is retained. The browser calls only `/health` for its backend health indicator; it never requests `/captures`.

## Production container

Build a static frontend image with the included multi-stage Dockerfile:

```powershell
docker build -t mirror-frontend ./frontend
docker run --rm -p 4173:8080 -e MIRROR_BACKEND_ORIGIN=http://host.docker.internal:8080 mirror-frontend
```

Nginx serves the static build, compresses CSS and JavaScript, applies baseline browser security headers, and falls back to `index.html` for client-side routes. The current local customer API rejects non-loopback requests and must not be exposed as a production customer API. A hosted customer journey needs an authenticated backend adapter first.

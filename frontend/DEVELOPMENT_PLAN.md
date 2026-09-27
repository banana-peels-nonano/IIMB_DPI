# Frontend development plan

## Guardrails

- Work only in `frontend/`; leave the existing Python backend unchanged.
- Use the installed UX4G design contract and the default UX4G theme.
- Keep the UI a renderer of the validated `mirror.app/1.0` contract. Do not derive financial facts, deadlines, statuses, balances, or claims in the browser.
- Clearly disclose replayed and simulated content. Never bundle raw AA responses, credentials, or real household state in the frontend.
- Commit and push each reviewable frontend feature to `gov-ux` before starting the next feature.
- Verify each major part with a production build and, where available, a local visual/browser check. Do not claim checks that could not be run.

## Phases and feature order

### Phase 0 — delivery plan

Create this plan before UI work. Record the API and security boundaries discovered in the repository.

### Phase 1 — frontend foundation

Create a React + TypeScript + Vite application under this folder. Pin `ux4g-web-components`, set the required `data-theme="light"` root, import the package stylesheet and runtime, and add a local proxy for the existing Flask `/health` route. No Python files, routes, or configuration are changed.

### Phase 2 — application shell and navigation

Build a responsive UX4G-based header, app navigation, accessible page container, demo/source disclosure, and route skeletons. Use routes instead of stateful tabs so screens can be linked and revisited.

### Phase 3 — local sample journey

Use a deliberately reviewed, synthetic sample contract shaped like `mirror.app/1.0`. Build these screens in the PDF's customer journey order:

1. Connect/demo disclosure (no real AA consent in this phase).
2. NOW cards and “Since last time”.
3. AHEAD conditional items.
4. OUR HOUSEHOLD recurring commitments, regular credits, observed protections, and pay-cycle information.
5. WHAT WE KNOW facts, corrections, purpose switches, access history, and Stop & Forget.

Answers, corrections, purpose toggles, and forgetting are in-memory demo interactions. Label them as simulated; they do not persist to or change the Python engine.

### Phase 4 — current-backend health integration

Use Vite's dev-server proxy to read the existing `GET /health` response without adding CORS configuration or changing Flask. Treat it only as a service-status indicator. Do not expose or consume `/captures` payloads from the browser.

### Phase 5 — contract API integration boundary

Implement and document a typed frontend data-source interface. Keep the local sample adapter as the active source. The repository has no endpoint that returns the Mirror contract or accepts customer actions, so a live adapter remains disabled until an approved backend/API exists. Expected future operations include reading the validated contract and submitting card answers, fact corrections, purpose choices, and forget requests.

### Phase 6 — live AA consent and secure sessions (future)

Requires an approved server-side API around the existing Anumati client and callback flow. The browser must never receive AA client secrets or raw retrieval credentials. A real OTP provider and server-managed session are required before real customer login; do not simulate successful authentication in the local demo.

### Phase 7 — hosting readiness (future)

Keep the frontend build static and environment-configured for a same-origin API. Confirm the deployment platform, data residency, session/cookie settings, logging, and security review with the hosting owner before production use.

## Current backend boundary

Existing Flask routes are `GET /health`, `GET /captures`, and `POST /aa/data-ready`, `/aa/consent`, and `/aa/callback`. They support local operations and Anumati callbacks. There is no customer API, browser authentication, or database. The Mirror engine has a validated JSON app contract and an out-of-repository JSON file store, but neither is exposed through Flask. Phases 1–4 therefore keep the backend unchanged and the user-facing journey on reviewed demo data.

## UX4G implementation inventory

- `Button`: Primary / medium for the main continue or answer action (`ux4g-btn ux4g-btn-primary ux4g-btn-md`); Outline Primary / medium for secondary navigation; Danger / medium for the final forget confirmation.
- `Card`: Solid / Vertical for information and action cards (`ux4g-card ux4g-card-solid ux4g-card-vertical`); responsive width is provided by UX4G layout utilities rather than a component size.
- `Alert`: Information (`ux4g-alert ux4g-alert-info`) for replay/simulation and connection disclosures; no size modifier.
- `Tag`: Tonal / Neutral / small (`ux4g-tag-tonal-neutral ux4g-tag-s`) for provenance labels. Each tag includes its O/R/I/U letter, full evidence label, and accessible description; colour is never the sole signal.
- Layout/navigation: UX4G grid and spacing utilities with semantic links; use application layout CSS only where the system has no matching page-shell pattern.

The complete class compositions above were checked against the pinned `ux4g-web-components@2.1.0` package README and stylesheet. For Button, preserve the base + variant + size order. Avoid UX4G form controls with the known low-contrast default border until a documented accessible token/class is confirmed; current sample answers use Buttons.

## Verification gates

- Each feature build must succeed before its commit/push.
- Inspect every changed screen at a narrow mobile width and a desktop width; check keyboard focus, labels, and the 44×44px target baseline.
- Check light and dark theme behavior if the component package supports both; the application default remains UX4G Light.
- Keep a git status check before each commit and confirm only `frontend/` files are included.
- Keep the demo fixture free of raw AA payloads and secrets.

## Status

- [x] Phase 0 — delivery plan.
- [x] Phase 1 — frontend foundation (React, TypeScript, Vite, UX4G 2.1.0, local health proxy; production build and mobile browser check passed).
- [ ] Phase 2 — application shell and navigation.
- [ ] Phase 3 — local sample journey.
- [ ] Phase 4 — current-backend health integration.
- [ ] Phase 5 — contract API integration boundary.
- [ ] Phase 6 — live AA consent and secure sessions (future; backend/API approval required).
- [ ] Phase 7 — hosting readiness (future).

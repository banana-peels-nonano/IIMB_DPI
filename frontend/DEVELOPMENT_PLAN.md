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

Implement and document a typed frontend data-source interface. Keep the read-only local sample adapter as the active screen source. The repository has no endpoint that returns the Mirror contract or accepts customer actions, so a live adapter remains disabled until an approved backend/API exists. Expected future operations include reading the validated contract and submitting card answers, fact corrections, purpose choices, and forget requests.

### Phase 6 — live AA consent and secure sessions (future)

Requires an approved server-side API around the existing Anumati client and callback flow. The browser must never receive AA client secrets or raw retrieval credentials. A real OTP provider and server-managed session are required before real customer login; do not simulate successful authentication in the local demo.

### Phase 7 — hosting readiness (future)

Keep the frontend build static and environment-configured for a same-origin API. Provide a multi-stage container and Nginx configuration with SPA route fallback, compression, baseline browser security headers, health checking, and a configurable private backend origin. Confirm the deployment platform, data residency, session/cookie settings, logging, and security review with the hosting owner before production use. Track UX4G's current production CSS output (about 8.3 MB uncompressed) and Vite's >500 kB chunk warning; Nginx gzip is configured, but verify compressed transfer and mobile performance on the chosen platform.

## Current backend boundary

Existing Flask routes are `GET /health`, `GET /captures`, and `POST /aa/data-ready`, `/aa/consent`, and `/aa/callback`. They support local operations and Anumati callbacks. There is no customer API, browser authentication, or database. The Mirror engine has a validated JSON app contract and an out-of-repository JSON file store, but neither is exposed through Flask. The frontend reads only the health boolean and uses reviewed sample data for customer screens. The hosting container is ready to serve the static app, but health status is not customer-data integration.

### Requirements before the live phases

To move Phase 6 past its local-demo boundary, the backend needs server-managed customer sessions and authentication (including a real OTP provider), a household-scoped endpoint returning only `validate_payload()`-approved `mirror.app/1.0` data, CSRF/session protections, and customer endpoints for allowed answers, fact corrections, purpose changes, and forgetting. It must keep AA credentials and raw retrieval data server-side, enforce consent before fetches, record the access/forget audit, and return safe errors and request identifiers. The frontend must then add a real source adapter, session-aware route guards, and explicit consent status/expiry states. The existing webhook callbacks are not customer endpoints, so the local demo must not imply live consent, fetched data, or persisted choices.

## UX4G implementation inventory

- `Button`: Primary / medium for the main continue or answer action (`ux4g-btn ux4g-btn-primary ux4g-btn-md`); Outline Primary / medium for secondary navigation; Outline Neutral / medium for clearing reversible demo choices. Medium targets are raised to at least 44px high to meet the touch target baseline.
- `Switch`: medium UX4G Switch (`ux4g-switch ux4g-switch-md`) for sample purpose controls, with semantic `role="switch"` and an accessible name. The package's neutral-subtle off track is a documented <3:1 boundary failure; a theme-aware Neutral Strong border is applied to the documented track element.
- `Card`: Solid / Vertical for information and action cards (`ux4g-card ux4g-card-solid ux4g-card-vertical`); responsive width is provided by UX4G layout utilities rather than a component size.
- `Alert`: Information (`ux4g-alert ux4g-alert-info`) for replay/simulation and connection disclosures; no size modifier.
- `Tag`: Tonal / Neutral / small (`ux4g-tag-tonal-neutral ux4g-tag-s`) for provenance labels. Each tag includes its O/R/I/U letter, full evidence label, and accessible description; colour is never the sole signal.
- Layout/navigation: UX4G grid and spacing utilities with semantic links; use application layout CSS only where the system has no matching page-shell pattern.

The complete class compositions above were checked against the pinned `ux4g-web-components@2.1.0` package README and stylesheet. For Button, preserve the base + variant + size order. Info and warning Alert bodies use UX4G's neutral-primary text utility because their default status-colour text measured below AA against the soft alert surface. Layout CSS is limited to page structure, fixed mobile navigation, target height, and the semantic-strong Switch track border required to address the documented off-track contrast defect.

## Verification gates

- Each feature build must succeed before its commit/push.
- Inspect every changed screen at a narrow mobile width and a desktop width; check keyboard focus, labels, and the 44×44px target baseline.
- Check light and dark theme behavior; the application defaults to UX4G Light and provides an in-demo theme control. Verified default Alert text contrast of 14.88:1 in Light and 5.20:1 for the warning alert in Dark; brand-neutral Alert text measures 5.84:1 in Dark.
- Check text and action target sizes; all `.ux4g-btn-md` actions are at least 44px high, mobile navigation links at least 46px, and purpose rows contain UX4G Switch controls.
- Keep a git status check before each commit and confirm only `frontend/` files are included.
- Keep the demo fixture free of raw AA payloads and secrets.

## Status

- [x] Phase 0 — delivery plan.
- [x] Phase 1 — frontend foundation (React, TypeScript, Vite, UX4G 2.1.0, local health proxy; production build and mobile browser check passed).
- [x] Phase 2 — application shell and navigation (UX4G responsive navigation, route-based journey, demo disclosure).
- [x] Phase 3 — local sample journey (reviewed synthetic scenarios, evidence labels, answer/fact controls, purpose choices that gate household sections, UX4G theme display control, and in-memory clear action).
- [x] Phase 4 — current-backend health integration (reads only `ok` from `/health`; offline journey remains available).
- [x] Phase 5 — contract API integration boundary (typed `mirror.app/1.0` DTO, fail-closed disabled live source, and separate active sample adapter).
- [ ] Phase 6 — live AA consent and secure sessions (blocked on server-managed sessions, real OTP, and approved customer API; do not present as live until those exist).
- [x] Phase 7 — frontend hosting packaging (static multi-stage container, same-origin health proxy, SPA fallback, gzip, health check, and baseline headers; production build and deep-link preview pass; container image itself was not built because Docker is unavailable in this workspace. Deployment target and live API remain operator/backend prerequisites).

# Frontend development plan

## Guardrails

- Keep interface changes in `frontend/`. Backend integration is additive and isolated to `aa-kit/customer_api.py` plus one blueprint registration; preserve every existing callback route and workflow.
- Use the installed UX4G design contract and the default UX4G theme.
- Keep the UI a renderer of the validated `mirror.app/1.0` contract. Do not derive financial facts, deadlines, statuses, balances, or claims in the browser.
- Clearly disclose replayed and simulated content. Never bundle raw AA responses, credentials, or real household state in the frontend.
- Commit and push each reviewable feature to `gov-ux` before starting the next feature.
- Verify each major part with a production build and, where available, a local visual/browser check. Do not claim checks that could not be run.

## Phases and feature order

### Phase 0 — delivery plan

Create this plan before UI work. Record the API and security boundaries discovered in the repository.

### Phase 1 — frontend foundation

Create a React + TypeScript + Vite application under this folder. Pin `ux4g-web-components`, set the required `data-theme="light"` root, import the package stylesheet and runtime, and add a local proxy for the existing Flask `/health` route. No Python files, routes, or configuration are changed.

### Phase 2 — application shell and navigation

Build a responsive UX4G-based header, app navigation, accessible page container, demo/source disclosure, and route skeletons. Use routes instead of stateful tabs so screens can be linked and revisited.

### Phase 3 — local engine journey

Build these screens in the PDF's customer journey order using `mirror.app/1.0`:

1. Connect/demo disclosure (no real AA consent in this phase).
2. NOW cards and “Since last time”.
3. AHEAD conditional items.
4. OUR HOUSEHOLD recurring commitments, regular credits, observed protections, and pay-cycle information.
5. WHAT WE KNOW facts, corrections, purpose switches, access history, and Stop & Forget.

The screens render the backend-generated synthetic replay. Actions go to the existing Mirror transition engine and durable store.

### Phase 4 — current-backend health integration

Use Vite's dev-server proxy to read the existing `GET /health` response without adding CORS configuration or changing Flask. Treat it only as a service-status indicator. Do not expose or consume `/captures` payloads from the browser.

### Phase 5 — validated local customer API

Add an isolated local-only Flask blueprint. Preserve `/health`, `/captures`, and all `/aa/*` handler implementations. Expose the existing `mirror.app/1.0` contract from the deterministic engine and validator. Generate synthetic AA-shaped data outside the checkout, keep state outside Git, and reject non-loopback requests. This mode must never read Anumati captures, credentials, or real household data.

### Phase 6 — functional local Mirror journey

The frontend uses the typed API source instead of hardcoded sample content. NOW, AHEAD, household, evidence, access history, and bounded facts come from the validated contract. Answers, fact corrections, the government-protection purpose switch, and Stop & Forget persist through engine/store operations. Disclose that this is synthetic and has no authentication or bank connection. AA replay source is fixed; do not present it as an AA consent control. Do not add pretend AA or LPG consent actions.

### Phase 7 — live AA consent and customer authentication (future)

Requires server-managed customer identity/session, an approved authentication journey, and verified correlation between Anumati callbacks, consent, and the household. Keep credentials and raw retrieval data server-side. The localhost API is synthetic-only and must not be reused for real data or deployed as an unauthenticated customer API.

### Phase 8 — hosting readiness (future)

Keep the frontend build static and environment-configured for a same-origin API. Provide a multi-stage container and Nginx configuration with SPA route fallback, compression, baseline browser security headers, health checking, and a configurable private backend origin. Confirm the deployment platform, data residency, session/cookie settings, logging, and security review with the hosting owner before production use. Track UX4G's current production CSS output (about 8.3 MB uncompressed) and Vite's >500 kB chunk warning; Nginx gzip is configured, but verify compressed transfer and mobile performance on the chosen platform.

## Current backend boundary

Existing Flask routes remain `GET /health`, `GET /captures`, and `POST /aa/data-ready`, `/aa/consent`, and `/aa/callback`; their handlers are unchanged. New loopback-only routes under `/api/customer` expose the validated contract and synthetic-only answer, correction, purpose, and forget actions. Their corpus and durable state are generated/stored outside the repository. There is no browser identity or real AA customer journey in this local mode. The hosting container's proxy does not make this API production-ready.

### Requirements before the live phases

Before any live household data can be served, implement server-managed authentication/sessions, a household-scoped API over only `validate_payload()`-approved data, CSRF/session protections, real consent correlation, and an authorized fetch path. Keep AA credentials and raw retrieval data server-side, enforce consent before fetches, record access/forget audits, and return safe errors. The frontend must then add authenticated routes and explicit consent status/expiry states. The webhook callbacks remain separate from customer routes. No OTP provider or customer identity configuration is present in this checkout.

## UX4G implementation inventory

- `Button`: Primary / medium for the main continue or answer action (`ux4g-btn ux4g-btn-primary ux4g-btn-md`); Outline Primary / medium for secondary navigation; Outline Neutral / medium for clearing reversible demo choices. Medium targets are raised to at least 44px high to meet the touch target baseline.
- `Switch`: medium UX4G Switch (`ux4g-switch ux4g-switch-md`) for sample purpose controls, with semantic `role="switch"` and an accessible name. The package's neutral-subtle off track is a documented <3:1 boundary failure; a theme-aware Neutral Strong border is applied to the documented track element.
- `Card`: Solid / Vertical for information and action cards (`ux4g-card ux4g-card-solid ux4g-card-vertical`); responsive width is provided by UX4G layout utilities rather than a component size.
- `Alert`: Information (`ux4g-alert ux4g-alert-info`) for replay/simulation and connection disclosures; no size modifier.
- `Tag`: Tonal / Neutral / small (`ux4g-tag-tonal-neutral ux4g-tag-s`) for provenance labels. Each tag includes its O/R/I/U letter, full evidence label, and accessible description; colour is never the sole signal.
- `Select`: native UX4G select (`ux4g-select ux4g-form-select`) for correcting bounded household facts.
- `Table`: Medium / column dividers (`ux4g-table ux4g-table-m ux4g-table-column-dividers`) for pay-cycle rows; the containing region scrolls horizontally on narrow screens.
- Layout/navigation: UX4G grid and spacing utilities with semantic links; use application layout CSS only where the system has no matching page-shell pattern.

The complete class compositions above were checked against the pinned `ux4g-web-components@2.1.0` package README and stylesheet. For Button, preserve the base + variant + size order. Info and warning Alert bodies use UX4G's neutral-primary text utility because their default status-colour text measured below AA against the soft alert surface. Layout CSS is limited to page structure, fixed mobile navigation, target height, and the semantic-strong Switch track border required to address the documented off-track contrast defect.

## Verification gates

- Each feature build must succeed before its commit/push.
- Inspect every changed screen at a narrow mobile width and a desktop width; check keyboard focus, labels, and the 44×44px target baseline.
- Check light and dark theme behavior; the application defaults to UX4G Light and provides an in-demo theme control. Verified default Alert text contrast of 14.88:1 in Light and 5.20:1 for the warning alert in Dark; brand-neutral Alert text measures 5.84:1 in Dark.
- Check text and action target sizes; all `.ux4g-btn-md` actions are at least 44px high, mobile navigation links at least 46px, and purpose rows contain UX4G Switch controls.
- Keep a git status check before each commit and confirm backend changes are limited to the additive API and registration.
- Keep generated demo state outside the git checkout and the fixture free of raw AA payloads and secrets.

## Status

- [x] Phase 0 — delivery plan.
- [x] Phase 1 — frontend foundation (React, TypeScript, Vite, UX4G 2.1.0, local health proxy; production build and mobile browser check passed).
- [x] Phase 2 — application shell and navigation (UX4G responsive navigation, route-based journey, demo disclosure).
- [x] Phase 3 — local sample journey (reviewed synthetic scenarios, evidence labels, answer/fact controls, purpose choices that gate household sections, UX4G theme display control, and in-memory clear action).
- [x] Phase 4 — current-backend health integration (reads only `ok` from `/health`; offline journey remains available).
- [x] Phase 5 — local customer API (loopback-only routes, validated engine contract, generated synthetic input and durable store outside the repository).
- [x] Phase 6 — functional local journey (contract-driven screens, engine-backed answers/corrections/purpose withdrawal/forgetting; no fake live connection).
- [ ] Phase 7 — live AA consent and customer authentication (requires an approved identity/session and consent-to-household design; not available in this checkout).
- [x] Phase 8 — frontend hosting packaging (static container, same-origin proxy, SPA fallback, gzip, health check, and baseline headers; container image not built because Docker is unavailable; local API must not be exposed as a production customer API).

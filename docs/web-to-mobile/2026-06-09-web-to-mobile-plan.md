# WebToMobile Plan: Khata (Expo React Native)

_Generated: 2026-06-09 · Source: local workspace (`~/dev/active/khata`)_

## Capabilities & Limits

- **Input tier:** Repo / local → **full source analysis**.
- **Can deliver:** a faithful native iPhone client (Expo React Native, also Android-capable) that talks to the existing Flask REST API; reuse of the API contract, domain semantics, and design tokens; a screen-by-screen rebuild of the UI.
- **Cannot deliver from code:** the vanilla HTML/JS frontend has no components/state to port — **all screens are rebuilt fresh** in React Native, using the web pages as visual/UX reference. Pixel accuracy and feel need human sign-off.
- **Stack chosen:** Expo React Native (TypeScript). **Auth chosen:** add a bearer-token endpoint to the Flask API.

## Source

- Backend: Flask (Python), ~3,685 LOC, SQLite (WAL).
- Frontend: 13 vanilla HTML pages + `assets/{nav,sharing}.js`, `{app,ledger}.css`. No JS framework, no package manifest.
- Domain: personal-finance ledger — plans (asset/loan/holding/chit/retirement), net worth, multi-currency FX, sharing/invitations, backup/restore.

## Audit Findings

### Stack & runtime
- **Backend:** Flask (Python). `[from-code]`
- **Frontend:** Vanilla HTML + CSS + JS, **no framework**. 13 static pages in `src/khata/static/`. `[from-code]`
- **DB:** SQLite (`khata_app.db`, WAL). `[from-code]`
- **Rendering model:** Server-coupled — Flask serves static HTML shells + JSON REST API consumed by page JS. `[from-code]`

### REST API (the reusable asset)
Blueprints under `src/khata/api/`:
- **auth:** `POST /register`, `POST /login`, `POST /logout`, `GET /me`, `POST /password`, `POST /profile`, `POST /avatar`, `GET /config`, `POST /google`
- **dashboard/networth:** `GET /api/dashboard`, `GET /api/networth`, `POST /api/base-currency`, `GET|POST /api/fx-rates`
- **plans (core):** `GET ""`, `POST ""`, `GET|PATCH|DELETE /<plan_id>`, installments, payments, `PATCH|DELETE /entries/<id>`, loan (disbursements/amortization/compare/collateral), holding (buys/sells/quote/refresh-quote), chit (entries/dividend), `POST /retirement/update`, members CRUD, accept/decline
- **analysis:** `GET /api/analysis/hold-vs-sell`
- **feed:** `GET /api/feed/config`
- **backup:** `GET /backup`, `POST /restore`
`[from-code]`

### Auth
- Server-side Flask sessions (`session["user_id"]`) via signed cookies; Google ID-token verify (`POST /google`); email/password (werkzeug hash). `KHATA_SECURE_COOKIES` + `ProxyFix`. `[from-code]`
- **Decision:** add bearer-token auth for mobile (see API Needs).

### Domain
Models: `user, plan, holding, chit, loan, retirement, ledger, fx, membership`. Multi-currency, sharing, backup. `[from-code]`

## Route To Mobile Navigation Map

Expo Router (file-based). Web routes → native screens:

| Web route | Mobile screen | Nav |
| --- | --- | --- |
| `/` (index/landing) | `(auth)/login` | Stack (unauth) |
| `/app` (dashboard) | `(tabs)/dashboard` | **Tab** |
| `/holdings` | `(tabs)/holdings` | Tab |
| `/analysis` | `(tabs)/analysis` | Tab |
| `/features` (net worth/feed) | `(tabs)/networth` | Tab |
| `/settings` | `(tabs)/settings` | Tab |
| `/create` | `create-plan` (modal) | Stack/modal |
| `/asset/<id>` | `plan/asset/[id]` | Stack push |
| `/loan/<id>` | `plan/loan/[id]` | Stack push |
| `/holding/<id>` | `plan/holding/[id]` | Stack push |
| `/chit/<id>` | `plan/chit/[id]` | Stack push |
| `/retirement/<id>` | `plan/retirement/[id]` | Stack push |

Bottom tab bar = primary nav (replaces `nav.js` top nav). Detail pages = stack pushes. Create = modal.

## Target Mobile Architecture

```
mobile/
  app/                      # Expo Router
    _layout.tsx             # root: auth gate + theme provider
    (auth)/login.tsx
    (tabs)/_layout.tsx      # bottom tabs
    (tabs)/{dashboard,holdings,analysis,networth,settings}.tsx
    plan/{asset,loan,holding,chit,retirement}/[id].tsx
    create-plan.tsx         # modal
  src/
    api/client.ts           # fetch wrapper + bearer token + base URL
    api/{auth,plans,dashboard,networth,analysis,feed,backup}.ts
    auth/session.ts         # SecureStore token storage
    theme/tokens.ts         # ported from app.css / ledger.css
    money/format.ts         # multi-currency formatting (port money.py rules)
    components/             # shared UI primitives
  app.json / eas.json
```

- **Data fetching:** TanStack Query over a typed fetch client. `[inferred]`
- **State:** server state via Query; local UI state via React state/context. `[inferred]`
- **Auth gate:** root layout redirects to login when no token.

## API Needs

| Endpoint | Mobile use | Auth/flags |
| --- | --- | --- |
| `POST /login`, `/register`, `/google` | sign in | **must return bearer token** (new) |
| `GET /me` | session bootstrap | Bearer |
| `GET /api/dashboard`, `/api/networth` | home/net worth | Bearer |
| plans CRUD + sub-resources | core features | Bearer |
| `GET /api/analysis/hold-vs-sell` | analysis | Bearer |
| `GET|POST /api/fx-rates`, `POST /api/base-currency` | currency | Bearer |
| `POST /avatar`, `POST /profile` | profile | Bearer + multipart |
| `GET /backup`, `POST /restore` | backup | Bearer + file |

**Backend changes required (small):**
1. Issue a bearer token on `/login`, `/register`, `/google` (e.g. `itsdangerous`/JWT signed token, or DB-backed token row).
2. Accept `Authorization: Bearer <token>` in the auth-required decorator **in addition to** the session cookie (keep web working).
3. **CORS** — allow the app origin / `*` for the API with `Authorization` header (mobile isn't same-origin).
4. Decide base URL config (dev: LAN IP:5057; prod: TLS host behind ProxyFix).

→ Record as **blocker until done**: mobile cannot authenticate without step 1–2.

## Reusable Code

- **REST API contract** — entire `src/khata/api/` surface reused as-is (plus token addition). `[from-code]`
- **Domain logic & money math** — `src/khata/money.py`, services/* stay server-side; mobile mirrors formatting rules only. `[from-code]`
- **Design tokens** — colors/spacing/typography from `assets/app.css` + `ledger.css` → `theme/tokens.ts`. `[from-code]`
- **Validation semantics** — request/response shapes from API blueprints → TS types. `[from-code]`

## Rewrite-Required Code

- **All 13 HTML pages** → React Native screens (no component reuse — vanilla HTML). `[from-code]`
- **`nav.js`** → Expo Router tab/stack navigation. `[from-code]`
- **`sharing.js`** → RN sharing/invitations UI calling members + accept/decline endpoints. `[from-code]`
- **CSS layouts** → `StyleSheet`/NativeWind; flex layouts re-expressed for RN. `[inferred]`
- **Forms** (create-plan, entries, login) → RN controlled inputs + validation. `[inferred]`

## Native Feature Gaps

| Feature | Web | Mobile approach |
| --- | --- | --- |
| Google sign-in | GIS web button | `expo-auth-session` Google provider → send ID token to `POST /google` |
| Avatar upload | file input | `expo-image-picker` → multipart `POST /avatar` |
| Backup export/restore | browser download/upload | `expo-file-system` + `expo-document-picker` |
| Token storage | cookie | `expo-secure-store` (Keychain) |
| Currency formatting | JS Intl | `Intl` (Hermes) or manual; verify locale support |

## Unknowns And Blockers

- **[BLOCKER]** Token auth endpoint not yet implemented (backend). `[from-code]`
- **[BLOCKER]** No CORS configured for cross-origin mobile calls. `[inferred]`
- **API response shapes** not yet typed — need to capture sample JSON per endpoint during build. `[inferred]`
- **Exact design tokens** (hex/spacing scale) must be extracted from CSS. `[from-code]`
- **FX rate source / refresh** behavior on mobile network. `[inferred]`
- **Backup file format** compatibility on device file system. `[assumption]`

## Implementation Checklist

> **Build status (2026-06-09):** Phases 0–5 **complete**; verify gate **passed**
> (`tsc --noEmit` clean + `expo export ios` bundles with no missing modules). Phase 6
> (avatar/backup native) **deferred to v1.1** — the read + create app is usable without it.
> Remaining: on-device smoke test against the updated backend. Live tracker:
> `docs/web-to-mobile/mobile-build-status.json` (served at `:5099/dashboard.html`).
> App lives in `mobile/`. Phases 1–5 checklist items below are all done.

**Phase 0 — Backend prep (blocker) ✅ DONE 2026-06-09**
- [x] Add bearer-token issue on `POST /login`, `/register`, `/google` in `src/khata/api/auth.py` — `[from-code]`
- [x] Accept `Authorization: Bearer` in auth — `[from-code]`
- [x] Add CORS (allow `Authorization`) for `/api/*` — `[inferred]`
- [x] Verify: token authenticates `/api/dashboard` with no cookie — `[from-code]`

> **Implementation notes (deviations from plan):**
> - Auth chokepoint was **`current_user()` in `api/auth.py`**, not `security.py` (which is only password helpers). Modifying that one function gave token auth to *every* protected route — all blueprints call it.
> - Token is **stateless** via `itsdangerous.URLSafeTimedSerializer` (new `src/khata/tokens.py`), signed with the existing `SECRET_KEY`, 30-day expiry. No DB table, no migration. Revoke-all = rotate SECRET_KEY.
> - CORS done **manually** in `__init__.py` (`after_request` + OPTIONS `before_request`) — avoided adding `flask-cors`. Wildcard origin, no `Allow-Credentials` (bearer, not cookie).
> - Web session-cookie auth untouched and still passing. 251/251 tests green (5 new).

**Phase 1 — Scaffold**
- [ ] `npx create-expo-app mobile` (TypeScript, Expo Router) under `~/dev/active/khata/mobile/` — `[inferred]`
- [ ] Add deps: `@tanstack/react-query`, `expo-secure-store`, `expo-auth-session`, `expo-image-picker`, `expo-file-system`, `expo-document-picker` — `[inferred]`
- [ ] `src/api/client.ts`: fetch wrapper, base URL from env, inject bearer — `[inferred]`
- [ ] `src/auth/session.ts`: SecureStore get/set/clear token — `[inferred]`

**Phase 2 — Auth flow**
- [ ] `app/(auth)/login.tsx`: email/password + Google sign-in → store token → `GET /me` — `[from-code]`
- [ ] Root `app/_layout.tsx`: auth gate redirect — `[inferred]`

**Phase 3 — Theme & API typings**
- [ ] Extract tokens from `assets/app.css`+`ledger.css` → `src/theme/tokens.ts` — `[from-code]`
- [ ] Port currency formatting rules from `src/khata/money.py` → `src/money/format.ts` — `[from-code]`
- [ ] Type API responses → `src/api/*.ts` modules per blueprint — `[from-code]`

**Phase 4 — Core screens (tabs)**
- [ ] `dashboard.tsx` ← `GET /api/dashboard` (mirror `static/app.html`) — `[from-code]`
- [ ] `networth.tsx` ← `GET /api/networth` (mirror `static/features.html`) — `[from-code]`
- [ ] `holdings.tsx` ← plans/holdings (mirror `static/holdings.html`) — `[from-code]`
- [ ] `analysis.tsx` ← `GET /api/analysis/hold-vs-sell` (mirror `static/analysis.html`) — `[from-code]`
- [ ] `settings.tsx` ← profile/avatar/base-currency/fx-rates/backup (mirror `static/settings.html`) — `[from-code]`

**Phase 5 — Plan detail + create**
- [ ] `plan/{asset,loan,holding,chit,retirement}/[id].tsx` ← `GET /<plan_id>` + sub-resources (mirror `*-detail.html`) — `[from-code]`
- [ ] `create-plan.tsx` modal ← `POST ""` plan create (mirror `create-plan.html`) — `[from-code]`
- [ ] Sharing UI: members + accept/decline (port `sharing.js`) — `[from-code]`

**Phase 6 — Native features**
- [ ] Avatar upload via `expo-image-picker` → `POST /avatar` — `[inferred]`
- [ ] Backup export/restore via file-system/document-picker — `[inferred]`

## Test Plan

- **Backend:** existing Python tests pass; add token-auth + CORS tests. `curl` smoke per endpoint with Bearer.
- **Mobile:** `npx tsc --noEmit` clean; `expo start` boots; Expo Go on-device smoke per screen.
- **Auth:** login (email + Google) → token persisted → relaunch stays signed in → logout clears.
- **Parity:** each screen visually compared to its web page (→ `mobile-parity-check`).
- **Release:** `mobile-qa-release` (build health, perf, a11y) before done.

## Acceptance Criteria

- [ ] Sign in (email/password + Google) on a real iPhone, session persists across relaunch.
- [ ] Dashboard, net worth, holdings, analysis, settings render real data from the API.
- [ ] Create + view + edit a plan (asset/loan/holding/chit/retirement).
- [ ] Multi-currency values format correctly; base currency switch works.
- [ ] Sharing: invite/accept/decline a plan member.
- [ ] `npx tsc --noEmit` clean; app boots in Expo Go with no red-box errors.

## Human Sign-Off Required

- Pixel/layout accuracy vs web pages (screen by screen).
- Brand colors & contrast on device (light/dark).
- Animation/scroll feel, tab transitions.
- Google sign-in works with real OAuth client on physical device.
- iPhone notch/safe-area handling; (optional) Android pass.

## Approval

**Implementation must not begin until you approve this plan.** Phase 0 (backend token + CORS) is a hard blocker — mobile auth is impossible without it.

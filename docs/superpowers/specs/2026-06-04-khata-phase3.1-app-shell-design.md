# Khata Phase 3 · Plan 3.1 — App Shell + Dashboard Design Spec

**Status:** Approved (autonomous) 2026-06-04. First plan of Phase 3 (app UI build-out). Builds on the
full Plans 1–2B backend. Frontend-only (no backend changes).

## Goal
Replace the placeholder `/app` with a real **authenticated app shell** — sidebar nav, topbar with the
signed-in user + logout, a **dashboard overview** (net worth + position cards), and a **plan list**
(filterable by type) — all wired to the existing read APIs. The shell every later Phase-3 page mounts in.

## Decisions (autonomous — recorded, not asked)
- **Client-side auth guard**, consistent with the existing static-page pattern: on load `GET
  /api/auth/me`; on `401` redirect to `/`. No server-side template/session gate (keeps pages static).
- **Single-page shell, no SPA framework** — hand-rolled HTML + vanilla JS on `ledger.css`, matching
  `holdings.html`/`index.html`. XSS-safe DOM rendering (never `innerHTML` user data — Plan-2B lesson).
- **Dashboard cards (4):** Net worth (`/api/networth.net_worth_minor`, in base currency) · Paid to date ·
  I owe · Owed to me (`/api/dashboard`). All formatted from integer minor units client-side.
- **Plan list** from `GET /api/plans` (`_summary` rows). Grouped/filtered **client-side** by type via
  chips (All / Assets / Loans / Holdings). Rows are **informational in 3.1** (name, type, currency,
  status, type-specific bits); per-plan detail pages arrive in 3.3–3.5, which will make rows clickable.
- **"New plan" button** links to `/create` (route + page land in Plan 3.2; a transient unbuilt link
  across one PR is acceptable for incremental delivery — noted).
- **Holdings** nav item links to the real `/holdings`; **Features** to `/features`; **Logout** posts
  `/api/auth/logout` then redirects to `/`.
- **Currency display:** show the user's base currency (from `/api/networth.base_currency`) as a badge;
  the INR/USD *theme* toggle (`data-cur`) is cosmetic and deferred (net worth is already base-converted).
- **Records/Settings/Chit/401(k) nav items** are shown but route to `#` (or `/holdings` where real)
  until their plans land — rendered as visibly "coming soon" so there are no broken-looking links.

## Components
- **Route:** `web.py` already serves `/app` from `app.html` — no route change; the file is replaced.
- **`static/app.html`** (replace 12-line placeholder): the shell. Sections — sidebar, topbar, dashboard
  cards, plan list. Loads `ledger.css` + app-specific styles.
- **JS flow:** `boot()` → `GET /api/auth/me` (401 → `/`) → in parallel `GET /api/networth`,
  `GET /api/dashboard`, `GET /api/plans` → render greeting, cards, base badge, plan rows → wire filter
  chips + logout.

## Data contracts consumed (all existing, unchanged)
- `GET /api/auth/me` → `{user:{id,email,display_name}}` | 401.
- `GET /api/networth` → `{base_currency, net_worth_minor, assets_minor, liabilities_minor, …}`.
- `GET /api/dashboard` → `{net_position_minor, i_owe_minor, owed_to_me_minor, paid_to_date_minor, plans:[…]}`.
- `GET /api/plans` → `{plans:[{id,type,name,currency,status, …type-specific}]}`.

## Money formatting (client)
A shared `fmtMinor(minor, ccy)` (minor/100, `en-IN` grouping, `₹`/`$` symbol, null→"—") and the
existing currency symbol map — same approach as `holdings.html`, with the `fmtMicro` null-guard applied
(Plan-2B follow-up).

## Testing (TDD, pytest — route/markup level; JS behavior is integration-tested via served HTML)
- `tests/test_web.py` (extend): `GET /app` → 200 and body contains the shell markers
  (`/api/auth/me`, `/api/dashboard`, `/api/networth`, `/api/plans`, `Net worth`, `ledger.css`, and the
  sidebar nav anchors `/holdings` + `/features`).
- A live-serve smoke (Task in the plan) registers a user, creates one asset + one loan + one holding,
  and confirms `/app` serves 200 and the three APIs it calls return 200 for that session.

## Out of scope (later Phase-3 plans)
Create-plan form (3.2) · per-plan detail pages + clickable rows (3.3–3.5) · sharing panel (3.5) ·
the cosmetic INR/USD theme toggle · Records/Proofs/Settings pages.

## Component boundaries
The shell depends only on the four read endpoints + `ledger.css`. No backend code changes; no new
routes (reuses the existing `/app`). All rendering is XSS-safe DOM construction.

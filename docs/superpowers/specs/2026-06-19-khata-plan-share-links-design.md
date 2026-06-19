# Shareable read-only plan views — link / print / send

**Date:** 2026-06-19
**Branch:** `feat/plan-share-links`
**Status:** approved design

## Problem

A user wants to share a plan (asset, loan, holding, chit, retirement) with someone who
isn't a Khata user — hand an asset statement to a bank/CA, print it, or WhatsApp it to
family. Today's sharing is **member-based only**: invite by email, recipient must log in
and accept. There is no public link, no print view, no "send as message".

## Goal

From any plan's detail page, a **Share** action offering three channels built on one
primitive (a read-only view of the plan):

1. **Read-only link** — a public, no-login, tokenized URL anyone with the link can open.
2. **Print** — a print-optimized rendering (token-less; prints the owner's own data).
3. **Send as message** — share the link via the OS share sheet (WhatsApp/SMS/email).

## Decisions (locked in brainstorming)

- **Access:** public, no login, via an unguessable token. Every link has an **expiry**
  (presets **7 / 30 / 90 days**) and is **revocable** anytime.
- **Scope (per-share toggle):** `summary` or `full`. `full` is **PII-redacted**.
- **Plan types:** all five (asset, loan, holding, chit, retirement) — one generic mechanism.
- **Data freshness:** **live** — the public view re-renders the plan's current state on
  each open (no stored snapshot). Revoke / expiry control exposure.

## Architecture

### 1. Data model — `plan_shares` (new table, migration required)

| column | type | notes |
|---|---|---|
| `id` | PK | |
| `plan_id` | FK → plans.id, ON DELETE CASCADE, indexed | |
| `token` | str, unique, indexed | URL-safe random, ≥128-bit (`secrets.token_urlsafe(32)`) |
| `scope` | str(8) | `'summary'` \| `'full'` |
| `expires_at` | datetime (tz) | |
| `revoked_at` | datetime (tz), nullable | revoke = set this |
| `created_by_user_id` | FK → users.id | |
| `created_at` | datetime (tz) | |

A link is **valid** iff `revoked_at IS NULL AND expires_at > now`. Multiple links per
plan allowed (e.g. one `summary`, one `full`, different expiries).

### 2. Service — `services/sharing_links.py` (new module; keeps `sharing.py` focused on members)

- `create_share(session, *, plan, user_id, scope, ttl_days) -> PlanShare` — validate
  `scope ∈ {summary, full}` and `ttl_days ∈ {7, 30, 90}`; generate token;
  `expires_at = now + ttl_days`.
- `list_shares(session, plan) -> list[dict]` — active + expired/revoked status for the
  manage panel (never returns the raw token for expired/revoked? — returns token only
  for currently-valid links so the UI can rebuild the URL).
- `revoke_share(session, *, plan, share_id) -> None` — set `revoked_at`.
- `resolve_public(session, token) -> (Plan, scope) | raises Gone/NotFound` — the public
  lookup: invalid token → NotFound (404); valid token but expired/revoked → Gone (410).
- `public_state(session, plan, scope) -> dict` — builds the **redacted** payload:
  - Dispatch on `plan.type` to the existing `*_state` serializer
    (`assets`/`loans`/`holdings`/`chits`/`retirement`).
  - **Always redact:** drop any contributor **emails** (the `*_state` outputs already
    carry display *names*, not emails — assert no email field leaks), and strip
    **proof** access (`has_proof` may stay as a boolean badge, but no `proof_ref` /
    attachment ids/urls). Never include the members list.
  - **If `scope == 'summary'`:** drop the line-by-line arrays (`ledger`, `schedule`,
    `deployed`, installment rows) — keep only headline figures (name, type, currency,
    status, current value / outstanding / totals, as-of date).
  - Include a small envelope: `{plan_type, name, currency, scope, as_of, owner_name,
    state: <scoped>}`.

### 3. Public access — `api/public.py` (new blueprint, registered in `__init__.py`)

- `GET /api/public/<token>` → `public_state` JSON. No auth. 404 invalid / 410 expired or
  revoked. No write methods exist on this blueprint.
- `GET /s/<token>` → serves a standalone **print-friendly** HTML page
  (`static/public-plan.html`) — no app shell, no nav, no auth guard. The page fetches
  `/api/public/<token>`, renders a type-aware read-only layout, and offers a **Print**
  button (`window.print()`). Shows a clean "link expired / not found" state on 410/404.

### 4. Owner-side share UI (all 5 detail pages)

Each `*-detail.html` gains a **Share** control opening a small menu/modal:
- **Create link:** scope (summary | full) + expiry (7 / 30 / 90 days) → `POST
  /api/plans/<id>/shares` (owner-only, reuses `_owned_plan`) → returns the share +
  full `/s/<token>` URL.
- **Copy link** (clipboard) and **Send…** (`navigator.share({url})` when available, else
  copy + toast).
- **Print** — token-less: opens/produces a print-optimized rendering of the *current*
  page's own data and calls `window.print()`. (Shared `@media print` CSS; the same
  layout the public page uses.)
- **Manage links** list: each active link with scope, expiry, created-at, and a
  **Revoke** button → `DELETE /api/plans/<id>/shares/<share_id>`.

Owner endpoints (in `api/plans.py`, owner-only):
- `POST /<plan_id>/shares` `{scope, ttl_days}` → `{share, url}`.
- `GET /<plan_id>/shares` → `{shares:[…]}`.
- `DELETE /<plan_id>/shares/<share_id>` → 204.

### 5. Print

Token-less by design. A shared `@media print` stylesheet (and/or a dedicated print
container) renders a clean statement: header (plan name, type, owner, as-of date,
currency), headline figures, and — for `full`/owner-print — the ledger/schedule table.
Hides nav, buttons, share UI. Works both on the owner's detail page and the public
`/s/<token>` page.

## Security

- Token = `secrets.token_urlsafe(32)` (≥128-bit entropy) — never a sequential id.
- Create/list/revoke are **owner-only** (`_owned_plan`); public routes are **read-only**,
  no auth, and expose only the scoped/redacted envelope — never emails, proof files,
  the members list, or any other plan.
- Expired/revoked → **410 Gone**; unknown token → **404**. No enumeration signal beyond
  that (random tokens make enumeration infeasible).
- `ON DELETE CASCADE` so deleting a plan kills its links.
- No write path is reachable via a token.

## Testing

Service (`tests/test_sharing_links.py`):
- create with each ttl preset; reject bad scope / bad ttl.
- `resolve_public`: valid → (plan, scope); expired → Gone; revoked → Gone; unknown → NotFound.
- `public_state` redaction: no email anywhere in output; no `proof_ref`/attachment ids;
  members list absent. `summary` omits `ledger`/`schedule`; `full` includes them.
- runs for all 5 plan types (smoke: each renders an envelope without error).

API (`tests/test_public_share_api.py`):
- `POST /shares` owner → 201 with url; non-owner → 403.
- `GET /api/public/<token>` valid → 200 scoped; expired → 410; revoked → 410; garbage → 404.
- leak assertions: response JSON contains no `@`-email and no proof url.
- `DELETE /shares/<id>` revokes → subsequent public GET → 410.

UI: headless verify the `/s/<token>` page renders for each plan type with 0 JS throws,
and the print layout (`@media print`) hides nav/share and shows the statement, per the
`/build-screen` protocol.

## Out of scope

- Frozen snapshots (chose live data).
- Login-required links (chose public).
- Editing/commenting via link (read-only only).
- Per-field custom redaction beyond the summary|full toggle.
- Analytics on link opens.

## Docs

Update `docs/specs/khata-AS-BUILT.md` (§9 + change log) and the data-model section
(new `plan_shares` table) in the same commit as the implementation.

# Khata Phase 3 · Plan 3.5 — Holding Detail + Sharing Panel Design Spec

**Status:** Approved (autonomous) 2026-06-04. Frontend-only. Last Phase-3 plan.

## Goal
A holding-plan detail page at `/holding/<id>` (position, value, gain, buy/sell/quote actions) **and** a
reusable **sharing panel** (`sharing.js`) surfaced on every plan-detail page — closing Plan-4 sharing in
the UI.

## Decisions (autonomous)
- **Route:** `/holding/<int:plan_id>` → static `holding-detail.html`; id from `location.pathname`; auth
  guard (401→`/`); non-holding → `/app`.
- **Read contract (K5):** `GET /api/plans/<id>` → `{plan:{…,asset_class,unit,symbol,current_price_minor},
  state:{asset_class,unit,symbol,purity,currency,qty_held_micro,avg_cost_per_unit_minor,cost_of_held_minor,
  current_price_minor,price_as_of,current_value_minor,unrealized_gain_minor,realized_gain_minor}}`.
- **Actions:** Buy → `POST /holding/buys {quantity,amount}`; Sell → `POST /holding/sells {quantity,amount}`;
  Set quote → `POST /holding/quote {price}`. Owner-only — non-owner sees a clean 403 inline.
- **Reusable sharing panel** `static/assets/sharing.js` exposing `mountSharing(planId, containerEl)`:
  fetches `/api/auth/me` + `GET /api/plans/<id>/members`; renders the member list (name · email · role
  badge); if the current user is the **owner** (matches the `role:"owner"` row's `user_id`), also renders
  an "add by email" input (`POST /members`) and a remove button per contributor (`DELETE
  /members/<user_id>`). Errors inline (`user_not_found`/`already_member`). All DOM via createElement (K4).
- The panel is mounted on **all three** detail pages (holding, asset, loan) via a `<div id="sharing">` +
  `<script src="/static/assets/sharing.js">` + `mountSharing(pid, document.getElementById("sharing"))`.

## Components
- `web.py`: `/holding/<int:plan_id>` → `holding-detail.html`.
- `static/assets/sharing.js`: the reusable panel (no framework).
- `static/holding-detail.html`: header, value/gain/qty cards, avg-cost + quote line, buy/sell/quote
  modal, `#sharing` container.
- `static/asset-detail.html`, `static/loan-detail.html`: add the `#sharing` section + script + mount.

## Testing (TDD)
- `tests/test_web.py`: `GET /holding/1` → 200 with `/holding/buys`, `/holding/quote`, `sharing.js`,
  `ledger.css`; and assert `asset-detail`/`loan-detail` now reference `sharing.js` (the panel is mounted
  everywhere). A `GET /static/assets/sharing.js` → 200 check.
- Done-gate: boot app, register owner + a second user, create a holding, buy + quote (state reflects),
  add the second user as a member (201), GET members shows 2, DELETE removes (200).

## Out of scope
Per-member contribution editing · invitations (existing-user-by-email only, as in Plan 4).

## Boundaries
`GET /api/plans/<id>`, `/holding/{buys,sells,quote}`, `/members` (POST/GET/DELETE), `/api/auth/me`,
`ledger.css`. No backend changes.

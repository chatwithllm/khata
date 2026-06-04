# Khata Phase 1 · Plan 4 — Sharing & Contributors Design Spec

**Status:** Approved 2026-06-04. Builds on Plans 1–3 (auth, asset+ledger, loan).

## Goal
Let users **share plans**, attribute each ledger entry to the user who logged it, derive each
contributor's **ownership share**, and roll everything up into a per-user **net-position dashboard**.

## Scope
**In:** `plan_memberships` table; owner-or-member access; member-can-add-own-payments while
owner-only for setup/membership; member-management endpoints; derived `contributors` in
`asset_state`; a `net_position` rollup service + `GET /api/dashboard`.

**Out (later):** manual ownership-share override · editing/deleting existing entries · invitations
(we add an existing user by email directly) · chit roll-up (chit not built) · per-user holdings/net
worth (holdings phase).

## Locked rules honored
- **Balances/shares derived, never stored** — ownership share and all dashboard figures are
  computed from the ledger each read. (rule #3)
- Money integer minor units; entry currency from the plan. (rules #2, #4)
- Per-payment attribution already exists: `ledger_entries.logged_by_user_id` (added in Plan 2).

## Data model
- New **`plan_memberships`**: `id`, `plan_id` (FK→plans ON DELETE CASCADE, indexed),
  `user_id` (FK→users, indexed), `role` (text, `'contributor'`), `created_at`.
  `UniqueConstraint(plan_id, user_id)`. The **owner is not a membership row** — ownership stays on
  `plans.owner_user_id` (no backfill of existing plans).
- `Plan` gains a `memberships` relationship (cascade delete-orphan).

## Access & permissions (API layer)
- `_accessible_plan(user, plan_id)` → the plan if `user` is the owner **or** has a membership; else
  `403`; `404` if missing. (Existing `_owned_plan` — owner-only — is kept for owner-restricted ops.)
- **Owner-or-member** (`_accessible_plan`): `GET /<id>` (detail), `GET` list shows owned + member
  plans, **`POST /<id>/payments`** (asset payment — attributed to the caller via
  `logged_by_user_id=user.id`), `GET /<id>/members`.
- **Owner-only** (`_owned_plan`): `POST /<id>/installments`, `POST /<id>/loan/disbursements`,
  `POST /<id>/loan/entries`, membership add/remove, and plan settings.
- `index` (`GET /api/plans`) returns plans where the user is owner **or** member.

### Membership endpoints (extend the `plans` blueprint)
- `POST /api/plans/<id>/members` — owner-only — `{email}`; looks up an existing user by email
  (404 `user_not_found` if none), adds a `contributor` membership (409 `already_member` on dup) →
  201 `{member:{user_id, email, display_name, role}}`.
- `GET /api/plans/<id>/members` — owner-or-member — `{members:[...]}` (includes the owner, marked
  `role:"owner"`, plus contributors).
- `DELETE /api/plans/<id>/members/<user_id>` — owner-only — removes a contributor → 200; 404 if not
  a member.

## Ownership share (derived) — `services/assets.py:asset_state`
`asset_state(session, plan)` gains a `contributors` list: group `out` ledger entries by
`logged_by_user_id`, sum each, compute `pct` (of paid_to_date, integer rounded, biggest-first),
and resolve `display_name` via `session.get(User, uid)`. Shape:
`contributors: [{user_id, display_name, paid_minor, pct}]`. (`asset_state` now genuinely uses its
`session` parameter — resolves the Plan-3 follow-up.) `funding_breakdown` is unchanged.

## Net-position dashboard — `services/dashboard.py:net_position(session, user_id)`
Pure; derived. Gathers the user's plans (owner OR member), then:
- `i_owe_minor` = Σ over plans the **user owns** that are loans with `direction='taken'`:
  `loan_state(...).total_minor` (principal_outstanding + interest_due).
- `owed_to_me_minor` = Σ over the user's owned loans with `direction='given'`: `total_minor`.
- `paid_to_date_minor` = Σ of `out` asset-payment amounts where `logged_by_user_id == user_id`
  (across owned + shared asset plans) — what *this* user has put in.
- `net_position_minor` = `owed_to_me_minor − i_owe_minor`.
- `plans` = a summary list (id, type, name, currency, role owner|member) for the user's plans.
Returns `{net_position_minor, i_owe_minor, owed_to_me_minor, paid_to_date_minor, plans:[...]}`.
`GET /api/dashboard` (auth-gated) → this object. Chit plans don't exist yet (skipped cleanly).

## Services / helpers
- `services/sharing.py` (pure): `add_member(session, *, plan, email) -> PlanMembership` (raises
  `MemberError`/`UserNotFound`/`AlreadyMember`), `remove_member(session, *, plan, user_id)`,
  `list_members(session, plan) -> list[dict]`, `accessible(session, *, plan, user_id) -> bool`
  (owner or member).
- `services/dashboard.py:net_position` (above).
- `asset_state` extended (above).

## Testing (TDD, pytest)
- `test_membership_models.py` — PlanMembership persists; unique(plan_id,user_id); cascade.
- `test_sharing_service.py` — add/remove/list members; `accessible` true for owner+member, false
  for stranger; add by unknown email raises; dup raises.
- `test_asset_service.py` (extend) — `contributors` breakdown: two users' payments → correct
  paid_minor + pct (You 58% / Priya 42%-style), names resolved, biggest-first.
- `test_dashboard_service.py` — rollup: owned loan-taken → i_owe; owned loan-given → owed_to_me;
  asset payments by the user → paid_to_date; net = owed − owe; member's shared asset appears in
  their plans list.
- `test_plans_api.py` (extend) — member can GET a shared plan + POST a payment (attributed) but is
  403 on installments/loan/members; non-member 403; owner adds/removes members; `GET /api/dashboard`.

## Migration & wiring
- One Alembic revision: `plan_memberships` table.
- `models/__init__.py` imports `PlanMembership`; `Plan.memberships` relationship.
- API: swap owner-only → `_accessible_plan` on read + asset-payment in `api/plans.py`; add the
  member endpoints to the `plans` blueprint. The dashboard is a **new blueprint `api/dashboard.py`**
  (`GET /api/dashboard`) registered in the app factory (the `plans` blueprint's `/api/plans`
  url_prefix can't host `/api/dashboard`).

## Component boundaries
`services/sharing.py` (membership logic) + `services/dashboard.py` (rollup) are pure + session-
injected. `asset_state` keeps its place in `assets.py`. The API layer adds access dispatch
(`_accessible_plan` vs `_owned_plan`) per endpoint. No business logic in HTTP handlers.

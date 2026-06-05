# Khata Phase 4 · Plan 4.1 — Chit Funds Design Spec

**Status:** Approved (autonomous) 2026-06-04. New `chit` plan type. Backend + UI.

## Chosen model (recommended, locked)
Khata tracks **the user's participation** in an auction chit (ROSCA) — their cashflows and derived net
position — rather than simulating the whole multi-member group. The auction itself is run externally
(by the foreman); the user records each month's outcome. The auction/dividend math is offered as a pure
**calculator** the UI uses to suggest amounts, but only the user's real cashflows are stored. This fits
the locked rules (one honest ledger; balances derived) and is tractable + correct, where a full
multi-member auction engine would be fragile and out of scope for a personal tracker.

**Why this over a full engine:** a self-hosted personal-finance app records *your* money. You know your
monthly subscription, the dividend the foreman credited you, and the month you took the prize — that is
exactly enough to derive your net position. Simulating every member's bid adds state we don't have and
don't need.

## Data model
- Reuse **`plans`** (`type='chit'`).
- New **`chits`** detail table: `plan_id` (PK, FK→plans CASCADE), `chit_value_minor` (BigInteger — the
  full monthly pot), `n_members` (Integer — members = months), `commission_bps` (Integer — foreman's
  commission as basis points of chit value; e.g. 5% = 500), `start_date` (Date).
- **Ledger** (`ledger_entries`, no schema change — `kind` is already free text): new kinds
  `chit_contribution` (direction `out` — your monthly subscription you paid),
  `chit_dividend` (direction `in` — dividend the foreman credited you),
  `chit_prize` (direction `in` — the prize you received the month you won).
- `Plan` gains a `chit` relationship (1:1, cascade delete-orphan).

## Derived chit state (`services/chits.py:chit_state(session, chit)`)
Pure; nothing stored beyond the entries. Let `c = chit`.
- `subscription_minor` = `round(chit_value_minor / n_members)` (Decimal; the gross monthly subscription).
- `total_contributed_minor` = Σ `chit_contribution` amounts (what you actually paid in).
- `total_dividends_minor` = Σ `chit_dividend` amounts (credited back to you).
- `prize_received_minor` = Σ `chit_prize` amounts (what you got when you won).
- `net_contributed_minor` = `total_contributed − total_dividends` (your effective outlay).
- `net_position_minor` = `prize_received + total_dividends − total_contributed`
  (positive = you're ahead — e.g. won early; negative = net paid in so far).
- `won` = `prize_received_minor > 0`.
- `months_recorded` = count of `chit_contribution` entries (rough progress vs `n_members`).
- A per-entry `ledger` list `[{kind, direction, amount_minor, occurred_at, note}]` for display.
Returns `{currency, chit_value_minor, n_members, commission_bps, subscription_minor,
total_contributed_minor, total_dividends_minor, prize_received_minor, net_contributed_minor,
net_position_minor, won, months_recorded, ledger:[...]}`.

## Auction/dividend calculator (`services/chits.py:auction_dividend(...)`, pure)
`auction_dividend(*, chit_value_minor, commission_bps, n_members, winning_bid_minor) -> dict`:
- `commission_minor` = `round(commission_bps/10000 × chit_value_minor)`.
- `dividend_pool_minor` = `max(0, winning_bid_minor − commission_minor)`.
- `dividend_per_member_minor` = `round(dividend_pool / n_members)`.
- `prize_minor` = `chit_value_minor − winning_bid_minor` (what the winner takes).
Returns those four. Exposed via `GET /api/plans/<id>/chit/dividend?bid=…` so the UI can suggest a member's
dividend + the prize for a given winning bid — **derived, not stored**. (All Decimal, no float.)

## Services (`src/khata/services/chits.py`, pure, session-injected)
- `create_chit_plan(session, *, owner_id, name, currency, chit_value_minor, n_members, commission_bps,
  start_date) -> Plan` — validates currency, `n_members ≥ 2`, `chit_value_minor > 0`,
  `0 ≤ commission_bps ≤ 10000`.
- `log_chit_entry(session, *, plan, user_id, kind, amount_minor, occurred_at, note=None) -> LedgerEntry`
  — `kind ∈ {chit_contribution, chit_dividend, chit_prize}`; direction `out` for contribution, `in`
  otherwise; validates `amount_minor > 0`; appends through `plan.ledger_entries` (stale-collection guard).
- `chit_state(session, chit) -> dict` (above). `auction_dividend(...)` (above).
Typed `ChitError`/`ValidationError`.

## API (extend `/api/plans` type-dispatch)
- `POST /api/plans` `type='chit'` `{name, currency, chit_value, n_members, commission, start_date}` →
  201 `{plan, state}` (`commission` is a human percent → `commission_bps` via `pct_to_bps`).
- `GET /api/plans/<id>` dispatch → `chit_state` for `type='chit'`.
- `POST /api/plans/<id>/chit/entries` `{kind, amount, occurred_at?, note?}` → 201 `{entry, state}`
  (owner-only).
- `GET /api/plans/<id>/chit/dividend?bid=<amount>` → `auction_dividend(...)` for that bid (owner-or-member).
- `_summary` for chit adds `{chit_value_minor, n_members, commission_bps}`.
- Error tuple includes `ChitError` (+ `ValueError`/`TypeError`).

## Frontend (`static/chit-detail.html` at `/chit/<id>`, + create-plan tab)
- `chit-detail.html`: header, cards (net position · prize received · net contributed), a status line
  (subscription · months recorded vs n_members · won?), a **dividend calculator** widget (enter a winning
  bid → shows dividend-per-member + prize, via the dividend endpoint), an entry modal (contribution /
  dividend / prize), and the entry ledger. Reuse `sharing.js`.
- `create-plan.html`: add a **Chit** tab (`chit_value`, `n_members`, `commission %`, `start_date`).
- `app.html`: chit rows already link to `/chit/<id>` (rows link by `p.type`); add a "Chit funds" filter
  chip + sidebar count.
- `web.py`: `/chit/<int:plan_id>` → `chit-detail.html`.

## Testing (TDD)
- `test_chit_models.py` — Chit persists; `kind` chit entries persist; `Plan.chit` cascade.
- `test_chit_service.py` — create; log contribution/dividend/prize; `chit_state` net math (won-early
  positive, net-paid negative); `auction_dividend` math (commission, pool, per-member, prize); validation
  (n_members≥2, bad kind, amount>0).
- `test_chits_api.py` — create-chit dispatch; entry endpoint; dividend endpoint; auth/ownership; asset/
  loan/holding still work.
- `test_web.py` — `/chit/1` 200 + markers.

## Migration & wiring
One Alembic revision: `chits` table (`down_revision` = Phase-2B head `26b0e2444049`). `models/__init__`
imports `Chit`; `Plan.chit`; api type-dispatch extends to asset|loan|holding|chit.

## Out of scope
Full multi-member auction simulation · foreman/organizer accounting across all members · per-member
roster. (The user records their own slot; the calculator covers the dividend math.)

## Boundaries
`money` (pure) ← `services/chits.py` (net + dividend math) ← `api/plans.py` (dispatch). `chit_state` +
`auction_dividend` independently testable.

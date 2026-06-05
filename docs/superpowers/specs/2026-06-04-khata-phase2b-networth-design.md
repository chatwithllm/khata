# Khata Phase 2 · Plan 2B — Net-Worth Consolidation + Cross-Currency Design Spec

**Status:** Approved 2026-06-04. Builds on Plans 1–5 + Plan 2A (holdings). Completes the
"Holdings & net worth" milestone.

## Goal
Consolidate the user's **holdings** (market value) and **loans** (given = asset, taken = liability)
into a single **net-worth** figure, reported in a per-user **base currency**, converting other
currencies via **manual FX rates** — valuing what can be valued and surfacing (never guessing) what
can't. Plus a live `holdings.html` net-worth page.

## Scope
**In:** `users.base_currency`; a global `fx_rates` table + FX service (`set_rate`/`get_rate`/
`convert`); a pure `net_worth(session, user_id)` consolidation; a new `networth` API blueprint
(`GET /api/networth`, `POST /api/base-currency`, `POST /api/fx-rates`); a wired `static/holdings.html`
(net-worth summary, holdings list, base/FX/quote controls) at `/holdings`.

**Out (later):** asset-purchase plans in net worth (excluded — they are acquisition goals);
shared/member holdings in net worth (holdings aren't shared yet — owned plans only); the
gold-loan-vs-selling analysis calculator; live spot-price / FX feeds; creating/buying holdings from
the UI (stays via the API + create flow); changing the existing `/api/dashboard` (`net_position`).

## Locked rules honored
- **No float.** Money = integer minor units; FX `rate_micro` = integer (base units per quote unit ×10⁶);
  conversion uses exact `Decimal`. (rule #2)
- **Balances/values derived, never stored.** Net worth, conversions, and buckets are computed each read
  from holdings + loans + the stored rate. The FX rate and the user's base currency are *inputs* (like a
  holding quote), not derived values. (rule #3)
- **Value what you can; surface the rest.** Unquoted holdings → `unpriced` (excluded). Currencies with
  no rate to base → an `unconverted` bucket (excluded from the base total). Nothing guessed.

## Data model
- **`User.base_currency`** — `Mapped[str]`, `String(3)`, `nullable=False`, `server_default='INR'`
  (existing rows backfill to INR). The currency the net-worth total is reported in.
- New **`fx_rates`** (global; FX is a market fact, not per-user): `id` (PK), `base_currency`
  (`String(3)`), `quote_currency` (`String(3)`), `rate_micro` (`BigInteger` — base units per **1** quote
  unit, ×10⁶; e.g. 1 USD = ₹83.42 → `83_420_000`), `as_of` (`DateTime(timezone)`),
  `UniqueConstraint(base_currency, quote_currency, name="uq_fx_pair")`.
- Two Alembic revisions (sequential): `users.base_currency`, then `fx_rates`. `down_revision` of the
  first = the Plan-2A head (`acec7de9fbe6`).

## FX service (`src/khata/services/fx.py`, pure, session-injected, no Flask)
- `set_rate(session, *, base, quote, rate_micro, as_of) -> FxRate` — upsert the directed
  `(base, quote)` rate (update `rate_micro`/`as_of` if the pair exists, else insert); validates
  `base`/`quote` ∈ `SUPPORTED_CURRENCIES`, `base != quote`, `rate_micro > 0`.
- `get_rate(session, base, quote) -> int | None` — the stored `rate_micro`, or `None` if unset. If
  `base == quote`, return `1_000_000` (identity).
- `convert(amount_minor, *, rate_micro) -> int` — `int((Decimal(amount_minor) * rate_micro / 1_000_000)
  .quantize(1, ROUND_HALF_UP))`.
Typed errors `FxError`/`ValidationError`. The human rate string (`"83.42"`) is parsed to `rate_micro`
via the existing `money.to_micro` at the API boundary (rejects float).

## Net-worth service (`src/khata/services/networth.py:net_worth(session, user_id) -> dict`)
Pure; derived. `base = user.base_currency`. Iterate the user's **owned** plans (via
`sharing.user_plans(...)[0]`):
- **Holding**: read `holdings.holding_state`. If `current_value_minor is not None` (quoted) → an asset of
  `current_value_minor` in `plan.currency`. If unquoted → append to `unpriced` and skip valuation.
- **Loan given** (`direction='given'`): asset (receivable) = `loan_state(...).total_minor`.
- **Loan taken** (`direction='taken'`): liability = `loan_state(...).total_minor`.
- **Asset purchase**: excluded (acquisition goal, not net worth).

For each valued amount in `ccy`:
- If a rate `get_rate(session, base, ccy)` exists (or `ccy == base`): convert to base and add to
  `assets_minor` or `liabilities_minor`.
- Else: add the original-currency amount to `unconverted[ccy]["assets_minor"]` /
  `["liabilities_minor"]` (excluded from the base totals).

`net_worth_minor = assets_minor − liabilities_minor` (base currency).

Returns:
```
{
  "base_currency": base,
  "assets_minor": <int>,            # in base
  "liabilities_minor": <int>,       # in base
  "net_worth_minor": <int>,         # in base
  "holdings": [                      # one row per owned holding plan
    {"id", "name", "asset_class", "currency", "qty_held_micro",
     "current_value_minor",         # original currency, null if unquoted
     "value_in_base_minor",         # null if unquoted OR no rate
     "unrealized_gain_minor",       # original currency, null if unquoted
     "priced": <bool>}
  ],
  "unpriced": [{"id", "name", "asset_class"}],
  "unconverted": {"<ccy>": {"assets_minor": <int>, "liabilities_minor": <int>}}
}
```

## API (new blueprint `src/khata/api/networth.py`, auth-gated)
- `GET /api/networth` → `200` `net_worth(g.db, user.id)`. `401` if unauthenticated.
- `POST /api/base-currency` `{currency}` → set `user.base_currency` (validate ∈ INR/USD; `400`
  otherwise) → `200 {base_currency}`. `401` if unauth.
- `POST /api/fx-rates` `{quote, rate, as_of?}` → upsert the rate from the caller's `base_currency` to
  `quote`: `rate_micro = to_micro(rate)`, `set_rate(...)` → `201 {base, quote, rate_micro}`. Errors
  (`FxError`/`ValueError`/`TypeError`) → `400`. `401` if unauth.
Registered in the app factory after the existing blueprints.

## Frontend (`src/khata/static/holdings.html`, served at `/holdings`)
Editorial-ledger page (links `/static/assets/ledger.css`), wired to live data:
- On load: `fetch('/api/networth')`; if `401`, redirect to `/`.
- **Net-worth summary** — assets / liabilities / **net worth** in `base_currency`; an **unconverted**
  callout per currency; a count/flag for **unpriced** holdings.
- **Holdings list** — each: name, asset_class, qty, current value (orig ccy), unrealized gain,
  value-in-base (or "no rate"); unpriced rows visibly flagged.
- **Controls** — a base-currency selector (`POST /api/base-currency`), an FX-rate input
  (`POST /api/fx-rates`), and a per-holding quote input (`POST /api/plans/<id>/holding/quote`); each
  re-fetches `/api/networth` on success. Error text via `textContent` (XSS-safe).
- `web.py` gains a `/holdings` route serving the file.

## Testing (TDD, pytest)
- `test_fx_service.py` — `convert` math (₹/$ round-trips), `set_rate` upsert (insert then update same
  pair, unique pair), `get_rate` (hit/miss/identity), reject `base==quote`/non-positive rate.
- `test_networth_service.py` — holdings (quoted) + loan-given as assets, loan-taken as liability, net =
  assets − liab; cross-currency conversion to base via a rate; **unpriced** holding excluded + listed;
  a USD plan with **no rate** → `unconverted["USD"]` (excluded from base totals); base-currency plans
  need no rate; asset-purchase plan excluded.
- `test_networth_api.py` — `GET /api/networth` (shape + 401); `POST /api/base-currency` (sets it, 400 on
  junk); `POST /api/fx-rates` (upsert, 400 on float/bad); after setting base+rate+quote, a USD holding
  shows up converted in `assets_minor`.
- `test_web.py` (extend) — `GET /holdings` → 200, body has net-worth markup + `/api/networth` +
  `ledger.css`.

## Migration & wiring
- Revision A: add `users.base_currency` (`server_default='INR'`, NOT NULL). Revision B: create
  `fx_rates`. (`render_as_batch=True` already enabled.)
- `models/__init__.py` imports `FxRate`.
- New `networth` blueprint registered in `create_app`.
- `web.py`: `/holdings` route.

## Component boundaries
`money.py`/`to_micro` (pure) ← `services/fx.py` (rate storage + conversion, session-injected) ←
`services/networth.py` (consolidation: reads `holding_state`/`loan_state`, converts via `fx`) ←
`api/networth.py` (HTTP + auth). `net_worth` is independently testable with fixed holdings/loans + a
fixed rate. The page depends only on the three endpoints + `ledger.css`.

## Next (later)
Gold-loan-vs-selling analysis · live spot/FX feeds · holdings in shared plans · asset-purchase net-worth
treatment · consolidating net worth into the main `/api/dashboard`.

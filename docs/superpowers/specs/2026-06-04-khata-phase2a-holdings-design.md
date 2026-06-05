# Khata Phase 2 · Plan 2A — Holdings Foundation Design Spec

**Status:** Approved 2026-06-04. Builds on Plans 1–5 (auth, asset+ledger, loan, sharing, google-auth).
First slice of the "Holdings & net worth" milestone; **Plan 2B** (net-worth consolidation + cross-currency
FX) builds on this.

## Goal
Add a **`holding` plan type** — a single market position (gold, silver, equity, MF, cash, …) tracked by
quantity and cost, with **average-cost** basis, a **manual latest-quote** valuation, and a fully
**derived** holding state (quantity held, cost of held, current value, realized + unrealized gain).
Reuses the Plan-2 plan/ledger spine. Backend only.

## Scope
**In:** `holdings` detail table; generic position model (`asset_class` + `unit` + optional `symbol`/
`purity`); buy/sell movements as ledger rows carrying `quantity_micro`; manual quote (latest price per
unit); derived `holding_state` (average-cost basis, realized/unrealized gain); holding-aware
`/api/plans` (create + state dispatch by type) + buy/sell/quote endpoints; integer-micro quantity
helpers.

**Out (later plans):** net-worth consolidation + cross-currency FX (**Plan 2B**); the rich
`holdings.html` UI (2B, once net-worth data exists to fill it); price history / live spot-price feeds;
dividends / interest / 401(k) contributions; FIFO lot tracking; tax/realized-gain reporting beyond a
simple average-cost figure.

## Locked rules honored
- **No float anywhere.** Money = integer minor units; **quantities = integer micro-units (×10⁶)**;
  rates already basis points. Valuation math uses `Decimal` (exact) → integer minor units. (rule #2)
- **Balances/values derived, never stored.** Quantity held, cost of held, current value, and gains are
  all computed from the ledger + the latest quote each read. The quote itself is an *input* (like a
  loan's rate), not a derived value — storing the latest manual price is allowed. (rule #3)
- **Original currency + amount immutable on a ledger entry.** (rule #4)
- **One honest ledger** — holding movements are `ledger_entries` rows distinguished by `kind`
  (`buy`/`sell`), not a separate table.

## Quantity model (no-float)
Quantities are stored as integer **micro-units**: scale `1_000_000` (6 decimal places). `92.5` grams →
`92_500_000`; covers gold to the milligram and MF units to 4 dp. Prices (`current_price_minor`) and
cash amounts (`amount_minor`) are money **per whole unit** / total cash, in integer minor units.

`src/khata/money.py` gains:
- `to_micro(value) -> int` — parse `"92.5"`/`"92.5"`-string/`int` → micro-units, `ROUND_HALF_UP`,
  **rejects `float`** and non-finite the same way `to_minor` does.
- `format_micro(micro) -> str` — `92_500_000` → `"92.5"` (trim trailing zeros, no float).

## Data model
- Reuse **`plans`** (`type='holding'`).
- New **`holdings`** detail table: `plan_id` (PK, FK→plans ON DELETE CASCADE), `asset_class`
  (text — one of `gold`/`silver`/`equity`/`mf`/`cash`/`other`), `unit` (text, e.g. `gram`/`share`/
  `unit`), `symbol` (text, nullable), `purity` (text, nullable), `current_price_minor` (Integer,
  nullable — latest manual quote, minor units **per whole unit**), `price_as_of` (DateTime(timezone),
  nullable).
- Extend **`ledger_entries`**: ADD `quantity_micro` (Integer, nullable) — set on `buy`/`sell` holding
  entries (null for asset/loan entries). `kind` gains values `'buy'`, `'sell'`.
- `Plan` gains a `holding` relationship (1:1, `uselist=False`, cascade delete-orphan), mirroring
  `asset`/`loan`.

### Direction wiring (service sets ledger `direction` from kind)
| kind | direction | amount_minor | quantity_micro |
|---|---|---|---|
| `buy` | `out` (cash spent to acquire) | cash cost | qty acquired |
| `sell` | `in` (cash received) | sale proceeds | qty sold |

## Derived holding state (`src/khata/services/holdings.py:holding_state(session, holding)`)
Pure; nothing stored. Let `buys` = `kind='buy'` entries, `sells` = `kind='sell'` entries.
1. `qty_bought_micro` = Σ buy.quantity_micro; `qty_sold_micro` = Σ sell.quantity_micro;
   `qty_held_micro` = `qty_bought_micro − qty_sold_micro`.
2. `cost_bought_minor` = Σ buy.amount_minor.
3. **Average cost** (Decimal): `avg_cost_per_unit` = `Decimal(cost_bought_minor) * 1_000_000 /
   qty_bought_micro` (minor units per whole unit), or `Decimal(0)` if `qty_bought_micro == 0`.
4. `cost_of_held_minor` = `int((avg_cost_per_unit * qty_held_micro / 1_000_000).quantize(1,
   ROUND_HALF_UP))`.
5. `proceeds_minor` = Σ sell.amount_minor;
   `realized_gain_minor` = `proceeds_minor − int((avg_cost_per_unit * qty_sold_micro / 1_000_000)
   .quantize(1, ROUND_HALF_UP))`.
6. **Valuation** (only if `holding.current_price_minor is not None`):
   `current_value_minor` = `int((Decimal(current_price_minor) * qty_held_micro / 1_000_000)
   .quantize(1, ROUND_HALF_UP))`; `unrealized_gain_minor` = `current_value_minor − cost_of_held_minor`.
   If no quote: both are `None`.
7. `avg_cost_per_unit_minor` (display) = `int(avg_cost_per_unit.quantize(1, ROUND_HALF_UP))`.

Returns `{asset_class, unit, symbol, purity, currency, qty_held_micro, avg_cost_per_unit_minor,
cost_of_held_minor, current_price_minor, price_as_of, current_value_minor, unrealized_gain_minor,
realized_gain_minor, proceeds_minor}`.

## Services (pure, session-injected, no Flask) — `src/khata/services/holdings.py`
- `create_holding_plan(session, *, owner_id, name, currency, asset_class, unit, symbol=None,
  purity=None) -> Plan` — validates `asset_class` ∈ the allowed set, `unit` non-empty, `currency`
  (reuse the asset/loan currency check); creates `Plan(type='holding')` + `Holding` row.
- `add_buy(session, *, plan, user_id, quantity_micro, amount_minor, occurred_at, note=None)
  -> LedgerEntry` — `kind='buy'`, `direction='out'`; validates `quantity_micro > 0`, `amount_minor > 0`.
- `add_sell(session, *, plan, user_id, quantity_micro, amount_minor, occurred_at, note=None)
  -> LedgerEntry` — `kind='sell'`, `direction='in'`; validates `> 0` and **rejects selling more than
  currently held** (`quantity_micro` ≤ `qty_held_micro` from a fresh `holding_state`).
- `set_quote(session, *, plan, price_minor, as_of) -> Holding` — sets `current_price_minor` +
  `price_as_of`; validates `price_minor >= 0`.
- `holding_state(session, holding) -> dict` (above).
Typed errors `HoldingError`/`ValidationError` (mirrors the asset/loan services).

## API (extend `/api/plans`, auth-gated)
- `POST /api/plans` — dispatch on `type`: add `'holding'`
  `{name, currency, asset_class, unit, symbol?, purity?}` → 201 `{plan, state}`. **Owner-only**
  (creator owns it).
- `GET /api/plans/<id>` — dispatch `state` by `plan.type` (`asset_state` | `loan_state` |
  `holding_state`). **Owner-or-member** (`_accessible_plan`), consistent with Plan 4.
- `POST /api/plans/<id>/holding/buys` — `{quantity, amount, occurred_at?, note?}` → 201
  `{entry, state}`. **Owner-only** (`_owned_plan`).
- `POST /api/plans/<id>/holding/sells` — same shape → 201. **Owner-only**.
- `POST /api/plans/<id>/holding/quote` — `{price, as_of?}` → 200 `{state}`. **Owner-only**.
- `quantity`/`amount`/`price` are human strings parsed server-side (`to_micro` for quantity,
  `to_minor` for amount/price). `occurred_at`/`as_of` reuse `_parse_dt`.
- Holding `_summary` adds `{asset_class, unit, symbol, current_price_minor}`.
- Error handling matches the existing handlers: `(PlanError, LoanError, HoldingError, ValueError,
  TypeError)` → 400 (the `TypeError` catch matters — `to_minor`/`to_micro` raise it on float input).

## Scope boundary (2A ↔ 2B)
2A does **not** modify `services/dashboard.py:net_position` or `GET /api/dashboard`. Rolling holdings'
`current_value_minor` into gross assets, and cross-currency FX consolidation, are **Plan 2B**. A holding
with no quote contributes nothing to value until priced — 2B decides how unvalued holdings surface.

## Testing (TDD, pytest)
- `test_money.py` (extend) — `to_micro`/`format_micro` round-trips (`"92.5"`→`92500000`→`"92.5"`),
  reject `float`, reject garbage, `ROUND_HALF_UP`.
- `test_holding_models.py` — `Holding` persists with its fields; `quantity_micro` on `ledger_entries`
  persists; `Plan.holding` relationship + cascade delete.
- `test_holding_service.py` — create holding; buy two tranches at different prices → correct
  `avg_cost_per_unit_minor` and `qty_held_micro`; set quote → `current_value_minor` +
  `unrealized_gain_minor`; sell part → `qty_held` reduced + `realized_gain_minor` at average cost;
  **oversell rejected** (`ValidationError`); unvalued (no quote) → `current_value_minor`/
  `unrealized_gain_minor` are `None`; float quantity/amount rejected (no-float guard).
- `test_holdings_api.py` — create-holding flow → buy → quote → state; dispatch on type (asset + loan
  still work); buy/sell/quote endpoints return updated state; auth (401) + ownership (403) on each new
  endpoint; validation (400) incl. float input and oversell.
- Full suite stays green (asset/loan unaffected by the new nullable `quantity_micro` + `kind` values).

## Migration & wiring
- One Alembic revision (batch mode already enabled): add `holdings` table; add
  `ledger_entries.quantity_micro` (nullable). `down_revision` = the Plan-5 head
  (`82264a4ffa8f`).
- `models/__init__.py` imports `Holding`; `Plan.holding` relationship added.
- `api/plans.py` extends the existing `type`-dispatch (asset|loan|holding) for create + detail; adds
  the three holding endpoints. No new blueprint.

## Component boundaries
`money.py` (pure, +quantity helpers) ← `services/holdings.py` (average-cost math + ledger writes,
session-injected) ← `api/plans.py` (HTTP + auth/ownership + type dispatch). `holding_state` is
independently testable with fixed entries + a fixed quote. Average-cost math lives only in
`holdings.py`.

## Next (Plan 2B)
Net-worth consolidation: gross assets (asset plans + holdings' current value) − liabilities (loans
owed) = net worth, with cross-currency FX rates; the rich `holdings.html` net-worth UI.

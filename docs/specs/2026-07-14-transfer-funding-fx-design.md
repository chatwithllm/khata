# Transfer funding-source + FX display fidelity — design

**Date:** 2026-07-14
**Status:** approved, pre-implementation
**Related:** [payment-chains](2026-07-08-payment-chains-design.md), [funding-3state](2026-07-08-funding-3state-design.md), [fx-snapshot](2026-06-11-fx-snapshot-design.md), [transit-panel-v2](2026-07-08-transit-panel-v2-design.md)

## Problem

Two defects surfaced on the asset detail screen's "Money in transit" panel, both distorting accounting when money is routed to a seller through a middleman (a payment chain).

### Defect 1 — no funding source on in-transit money

When money is sent through a middleman (e.g. Chamu → Dheeraj → seller), there is nowhere to record where the sender's money came from (loan / savings / etc.).

- `TransferHop` / `HopSource` have no `funding_source` or `funding_plan_id` column. Only `LedgerEntry` does.
- The compose form *shows* a Funding-source dropdown and even POSTs `funding_source` for a transit hop, but `create_hop` only consumes it when the hop `is_terminal` (→ `fan_out_terminal`). For a non-terminal hop the value is **silently discarded**.
- The hop editor slide-over has no funding-source field at all, and `update_hop` does not accept one.
- Even at the terminal hop, `fan_out_terminal` stamps **one** `funding_source` across **all** contributors and passes **no `funding_plan_id`** to `log_payment` — so "this money came from *this specific loan*" is impossible for any money that flowed through a chain, and the loan-deployment link never lights up.

Consequence: money routed through a middleman cannot be tagged as coming from a loan, and the loan cannot show it was deployed toward the asset.

### Defect 2 — in-transit USD figures don't match what was entered

A hop entered as `$1000 @ ₹94.47` displays as **$988**, `$1500 @ 94.97` as **$1490**, `$2000 @ 94.96` as **$1985**, etc.

- Plan base currency = INR; the user's display currency = USD.
- The stored INR is **correct**: `$1000 @ 94.47` → `94,470` INR. The distortion is purely at display.
- Transit rows (and ledger rows) render `conv(amount_minor)`, which converts INR→USD using **one global snapshot rate** (`FXR_MICRO`, ≈ ₹95.64/$), **not** the rate the money was actually sent at. `94,470 ÷ 95.64 = $988`.
- `plan_transfers` does not even emit each hop's `fx_rate_micro` / `fx_counter_currency`, so the frontend cannot round-trip back to the entered amount.

Confirmed by reconstruction: displayed = `entered × entered_rate ÷ 95.64` for every row.

## Decisions (locked)

1. **FX display:** each transaction shows at **its own stored send-rate** (round-trips exactly to the amount typed). Aggregates that mix transactions stay on the single global snapshot rate.
2. **Funding source:** captured **at the origin hop** (where the sender's own money enters the chain), and auto-traced forward to the terminal ledger entries.
3. **Existing closed chains:** editing an origin hop's funding fields **re-stamps** the already-created downstream ledger entries in place (no delete/re-log).
4. **Fan-out granularity:** one ledger entry per **(contributor, funding_source, funding_plan_id)**. A contributor whose money came from more than one source gets more than one entry (accepted tradeoff for exactness).

## Part A — FX display (native per-transaction rate)

No schema change: `TransferHop.fx_rate_micro` and `TransferHop.fx_counter_currency` already exist and are set by `create_hop` (`transfers.py:130-132`). `fx_rate_micro` is stored as **counter-per-entry ×1e6** (same convention as `LedgerEntry`), and `fx.convert(amount_minor, rate_micro=…)` already derives the native counter value (see `_entry_json.counter_value_minor`).

### A1. Emit hop FX trio

`transfers.plan_transfers` hop-row dicts gain, mirroring `_entry_json`:

```python
"fx_rate_micro": h.fx_rate_micro,
"fx_counter_currency": h.fx_counter_currency,
"counter_value_minor": (fx.convert(h.amount_minor, rate_micro=h.fx_rate_micro)
                        if h.fx_rate_micro else None),
```

`outstanding_minor` / `consumed_minor` remain INR — those are chain-math quantities, not display-native. Only the hop's headline amount gets a native counter value.

### A2. Native display helper (frontend)

Add a `dispAmount(row)` helper used wherever a **single transaction's** amount is shown:

```js
function dispAmount(row){
  if(DISP === row.fx_counter_currency && row.counter_value_minor != null)
    return row.counter_value_minor;      // native: round-trips to what was entered
  return conv(row.amount_minor);          // no per-txn rate → global snapshot
}
```

Apply to:
- transit-panel hop rows (`transfers.js` render, via the injected `fmt`/amount path),
- ledger rows (`asset-detail.html:839`, currently `conv(lr.amount_minor)`) — same latent bug.

`sym(DISP)` and `fmtNum` usage is unchanged; only the minor value feeding them changes.

### A3. Aggregates stay on the global snapshot

Totals mix transactions at different rates and can only be expressed at one rate. Left on `conv()`:
- header paid-to-date / remaining / projection,
- "in transit" total and per-contributor in-transit,
- contributor sums, funding-source bars/segments.

Because per-row native amounts and aggregate snapshot amounts use different rates, rows will not sum exactly to the totals. Add one quiet sub-note near the totals — "converted at current rate" — so the discrepancy is explicit rather than looking like a bug.

### A4. Terminal breakdown line

The terminal breakdown ("= $988 from Chamu + $1,986 from Narshima + …") is built from `resolve_contributions` (INR portions) then `conv()`-ed. Each portion is traced to an origin hop; convert each portion at **that origin hop's** native rate when `DISP` matches its `fx_counter_currency`, else fall back to `conv()`. (Requires the breakdown builder to know each portion's origin hop — see Part B, where `resolve_contributions` already walks to origins.)

## Part B — funding source through chains

### B1. Schema

Add to `transfer_hops` (one Alembic migration):

- `funding_source VARCHAR(20) NULL` — same vocabulary as `LedgerEntry.funding_source` (`savings`, `loan`, `borrowed`, `sold_asset`, `chit_payout`, `other`). NULL = untagged.
- `funding_plan_id INTEGER NULL` FK → `plans.id` — the specific loan the own-funds portion came from, when `funding_source ∈ {loan, borrowed}`.

Semantics: these describe the **own-funds portion** of the hop (the `HopSource` row with `source_hop_id IS NULL`). A hop that only forwards upstream money (no own funds) leaves them NULL and inherits provenance from upstream via tracing.

### B2. Capture — service

`create_hop(...)` and `update_hop(...)` accept `funding_source=None`, `funding_plan_id=None` and store them on the hop.

- `create_hop`: replace the current single `funding_source="other"` fan-out parameter. The value now lives on the hop; fan-out reads each origin's stored value (see B4). The terminal hop's *own* top-up (its own-funds source) is tagged by the terminal hop's own `funding_source`.
- `update_hop`: setting/changing `funding_source` or `funding_plan_id` is allowed even when the hop is consumed or terminal (unlike amount edits), and triggers re-stamp (B5).
- Validation: `funding_plan_id` must reference an accessible loan plan; only meaningful when `funding_source ∈ {loan, borrowed}` (mirror `fundSrcIsLoan`), else stored NULL.

### B3. Capture — UI

- **Compose form (Recipient = transit):** keep the existing `#fsource` dropdown (stop discarding it) and reveal the existing "from which loan" picker (`#fundplan-fld`) on `loan`/`borrowed`, exactly as the direct-payment path already does. `saveHop` sends `funding_source` (already in body) plus `funding_plan_id`.
- **Hop editor slide-over (`#hop-over`, `asset-detail.html:256-284`):** add a Funding-source select and a "from which loan" picker mirroring the compose form. PATCH `/hops/{id}` relays both.
- **Display:** a hop/ledger row with `funding_source` set shows the existing source pill (`srcLabel`) and, when funded from a loan, the existing loan-deployment link pill. Untagged rows show no pill.

### B4. Attribution — fan-out threads provenance

`resolve_contributions` and `_alloc` currently return `(uid, amount)`. Extend to carry funding provenance from the own-funds source that produced each portion:

```
(uid, funding_source, funding_plan_id, amount)
```

- When `_alloc` / `resolve_contributions` reaches an own-funds source (`source_hop_id IS NULL`) on hop `h`, it emits `(h.from_user_id, h.funding_source, h.funding_plan_id, grab)`.
- Merge key becomes `(uid, funding_source, funding_plan_id)` instead of `uid`.

`fan_out_terminal` creates one `LedgerEntry` per merged group:

```python
for (uid, fsrc, fplan, amt) in resolve_contributions(session, hop):
    entry = log_payment(session, plan=plan,
        user_id=uid if uid is not None else hop.logged_by_user_id,
        amount_minor=amt, occurred_at=hop.occurred_at, method=hop.method,
        funding_source=fsrc or "other",
        funding_plan_id=fplan,               # NEW: threads the loan link
        proof_ref=hop.proof_ref, note=hop.note, acting_user_id=acting_user_id)
    entry.source_hop_id = hop.id
```

`log_payment` already accepts `funding_plan_id` (`assets.py:153`) and snapshots the entry FX rate — no signature change needed there. Non-user origins fall back to the hop logger (unchanged) with `funding_source="other"`, `funding_plan_id=None`.

The `in_transit_by_contributor` attribution (`plan_transfers`, using `_alloc`) keeps aggregating by uid only — provenance is irrelevant for the in-transit total. It just ignores the extra tuple fields.

### B5. Re-stamp on edit (fix existing closed chains)

When `update_hop` changes `funding_source` or `funding_plan_id` on a hop whose money has already fanned out downstream:

1. Find the affected terminal hop(s): terminal hops reachable downstream from the edited hop (follow `HopSource` consumers transitively to `is_terminal` hops). In practice the edited origin hop belongs to exactly one chain.
2. For each affected terminal hop `T`, recompute `resolve_contributions(T)` under the new provenance and **reconcile** only its fan-out-generated ledger entries — those with `kind='payment'`, `source_hop_id == T.id`:
   - match recomputed group `(uid, fsrc, fplan)` to an existing entry by `(user_id, source_hop_id)` and, where possible, the prior grouping; update `funding_source` / `funding_plan_id` in place;
   - if the new grouping splits one contributor into multiple `(fsrc, fplan)` groups (or merges), delete/insert entries to match the recomputed set, preserving amounts;
   - preserve `proof_ref` / receipt state on entries whose identity is unchanged.
3. Manually-added ledger entries (no `source_hop_id`, or `source_hop_id` outside the affected set) are never touched.
4. Write the usual audit record for the hop edit.

This is the highest-risk unit. Keep it isolated in a dedicated service function (`restamp_downstream(session, hop, acting_user_id)`) with its own tests, and scope its writes strictly to fan-out-generated entries.

### B6. Data / migration

- No backfill of `funding_source`. Existing hops default NULL (shown untagged) until the user edits them; the edit re-stamps their closed chains.
- Migration adds the two columns and the FK; safe on the live SQLite DB (nullable, no default rewrite).

## Testing

- `create_hop` / `update_hop` persist `funding_source` + `funding_plan_id`.
- Transit hop no longer discards `funding_source` (regression on the "silently dropped" bug).
- Fan-out splits per `(uid, funding_source, funding_plan_id)`; a contributor with two differently-funded origin hops produces two ledger entries with the right provenance and a correct amount split.
- `funding_plan_id` propagates to the ledger entry and lights up the loan-deployment link.
- Re-stamp: editing an origin hop updates downstream fan-out entries in place; grouping split and merge both handled; manual entries untouched; proof/receipt preserved.
- FX: `plan_transfers` emits the hop FX trio; `counter_value_minor` round-trips (`$1000 @94.47` → `$1000.06`); `dispAmount` picks native when `DISP == fx_counter_currency`, global otherwise; ledger rows use the same helper.

## Out of scope

- Storing the original entered currency+amount as the source of truth (INR remains canonical; USD is derived per-transaction).
- Reconciling aggregate totals to the sum of per-row native amounts (impossible across mixed rates; surfaced via the "at current rate" note instead).
- Any change to non-payment ledger kinds (`transfer_fee`, etc.) beyond inheriting the threaded provenance already flowing through fan-out.

## Files touched (anticipated)

- `alembic/versions/<new>_hop_funding_source.py` — migration.
- `src/khata/models/transfer.py` — two columns on `TransferHop`.
- `src/khata/services/transfers.py` — `create_hop`, `update_hop`, `resolve_contributions`/`_alloc`, `fan_out_terminal`, new `restamp_downstream`, `plan_transfers` FX trio.
- `src/khata/api/transfers.py` — relay `funding_source` / `funding_plan_id` on create + patch.
- `src/khata/static/asset-detail.html` — compose-form transit funding fields, hop-editor funding fields, `dispAmount` helper + row wiring, "at current rate" note.
- `src/khata/static/assets/transfers.js` — hop-row amount rendering via `dispAmount`.
- `docs/specs/khata-AS-BUILT.md` + this design's cross-refs — update.

## Verification

Run `/build-screen` headless verification of the asset-detail "Money in transit" panel and the funding-source flow before marking done, per project rule.

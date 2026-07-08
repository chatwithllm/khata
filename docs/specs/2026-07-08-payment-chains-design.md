# Payment Chains (Transfer Routing) — Design

**Date:** 2026-07-08
**Status:** Approved design, pre-implementation

## Problem

Money for a shared purchase rarely flows in one hop. Buyer2 sends 10k to
buyer1; buyer1 forwards 9k to the seller; 1k sits with buyer1. Or money
passes through a middleman who hands cash to the seller. Today khata records
only the final "X paid Y toward plan" fact — the route is invisible, transit
money is untracked, and attribution of merged transfers is manual.

## Goals

1. **Route capture** — every hop (who → whom, amount, date, method, proof,
   note) recorded with full detail. Hops can be days apart.
2. **Correct attribution** — plan paid-totals credit the *ultimate origin*
   of the money, and only when it *reaches the seller*. Buyer2's 10k sent to
   buyer1 counts as buyer2's contribution only for the 9k that was forwarded.
3. **In-transit visibility** — money that left someone's hand but hasn't
   reached the seller is visible per plan, never counted in paid totals.
4. **Merged transfers** — one physical transfer can carry multiple people's
   money (buyer2 sends 20k: his 10k + buyer1's 10k). Split attribution.
5. **Remainders resolve** — leftover in-transit money can be forwarded
   later, returned to origin, or written off as a fee.

Applies to **all plan types** (assets, loans, chits, …), not just asset
purchases.

## Non-goals

- No changes to how plan totals are computed (ledger entries stay the single
  source of truth for paid amounts).
- No graph-canvas chain editor; a simple vertical timeline suffices.

## Data model

### `transfer_hops` (new)

One row per hop.

| field | type | notes |
|---|---|---|
| id | PK | |
| plan_id | FK plans, CASCADE | chain belongs to a plan; tags intent ("this money is for plan X") independent of recipient |
| chain_id | int | groups hops of one chain; equals the first hop's id |
| from_user_id / from_contact_id / from_name | FK users / FK contacts / text | exactly one non-null |
| to_user_id / to_contact_id / to_name | same | exactly one non-null |
| amount_minor | bigint | hop's own amount |
| currency | char(3) | |
| fx_rate_micro / fx_counter_currency | bigint / char(3) | same FX-snapshot pattern as ledger entries (derived counter value, never stored) |
| occurred_at | datetime tz | |
| method | varchar(20) | bank / cash / … (same vocab as entries) |
| proof_ref | text | |
| note | text | |
| is_terminal | bool | recipient is the seller → money delivered |
| receipt_status | varchar(12) | `agreed` / `pending` / `countered` |
| counter_amount_minor | bigint nullable | receiver's counter-claim |
| resolution | varchar(12) nullable | null (open) / `forwarded` / `returned` / `fee` — resolution of a hop's *remainder* |
| logged_by_user_id | FK users | |
| created_at | datetime tz | |

### `hop_sources` (new)

Split attribution: which upstream money a hop consumes.

| field | type | notes |
|---|---|---|
| id | PK | |
| hop_id | FK transfer_hops, CASCADE | the downstream (consuming) hop |
| source_hop_id | FK transfer_hops, nullable | NULL = `from` party's own funds |
| amount_minor | bigint | how much drawn from that source |

Constraint: Σ `hop_sources.amount_minor` for a hop = the hop's
`amount_minor` (a hop's money is fully accounted: own funds + upstream).

**Derived, never stored:**
`outstanding(hop) = amount_minor − Σ amount_minor of hop_sources rows where source_hop_id = hop.id`

### `transfer_hop_audit` (new)

Mirror of `ledger_entry_audit`: immutable create/edit/delete records, JSON
snapshot + diff, `hop_id` SET NULL on delete, `plan_id` kept for history.

### `ledger_entries` (extended)

- New nullable column `source_hop_id` → FK `transfer_hops`. Set on entries
  spawned from a terminal hop. Existing entries unaffected.

### Plan memberships (extended)

- New role `seller`. Assigned by owner/admin to an existing user, or the
  seller registers via the existing invitation flow with the seller role.

## Attribution & totals flow

- **Plan paid-total = ledger entries only. Unchanged.** Entries are spawned
  only when a terminal hop is saved.
- A terminal hop with source breakdown creates **one ledger entry per
  ultimate contributor**. Ultimate contributor = walk `hop_sources` upstream
  until `source_hop_id IS NULL`; that row's hop `from` party (or the
  terminal hop's own `from` for its own-funds portion) is the contributor.
  - Example: terminal 20k to seller, sources = 10k from buyer1's hop +
    10k own (buyer2) → two entries: buyer1 10k, buyer2 10k. Both carry the
    same `source_hop_id` and share the hop's proof.
  - Contributors that are contacts / free-text (no user account) still get
    an entry attributed via the entry's existing attribution mechanism;
    `logged_by_user_id` = the user who logged the terminal hop.
- **Count timing:** contribution counts when money reaches the seller
  (terminal hop), not when it leaves the contributor's hand.
- **In-transit KPI** per plan: Σ `outstanding` of open (`resolution IS
  NULL`) non-terminal hops. Displayed beside paid/remaining; never added to
  paid.
- **Remainder resolutions** (acting on a hop's outstanding amount):
  - `forwarded` — consumed by a later hop (`hop_sources` row); resolution
    set automatically when outstanding reaches 0.
  - `returned` — a return hop back to the origin party; the chain's
    outstanding shrinks; contribution never counted.
  - `fee` — creates a ledger entry `kind='fee'` attributed to the ultimate
    origin contributor (counts as their spend on the plan, flagged as fee,
    not purchase payment).

## Confirmation & guards

- **Hop receipt:** receiver is a registered user → `receipt_status =
  pending` until they confirm; receiver is contact/free-text → auto
  `agreed`. Counter flow mirrors entry amount confirmation: receiver
  counters ("got 9k not 10k"), logger accepts or re-counters.
- Terminal-hop ledger entries follow existing entry confirmation rules
  unchanged.
- **Integrity guard:** a hop cannot be deleted or edited below its
  already-consumed amount while downstream `hop_sources` reference it.
  Downstream must be unwound first.
- All hop mutations audited in `transfer_hop_audit`.

## Terminal detection

- Hop's `to` matches the plan's seller (seller contact on asset, or a
  seller-role member) → `is_terminal` auto-set.
- Manual "this is the final payment" override available for free-text
  recipients.

## UI

1. **Log-payment form** — recipient step: "Paid to seller (final)" vs
   "Sent to person (in transit)". Final → optional "draw from in-transit"
   picker listing open hops with outstanding amounts; pre-fills the split.
   Recipient and purpose are separate: recipient = who physically received,
   plan = what the money is for.
2. **Money-in-transit panel** on plan detail: open hops, per-hop
   outstanding, who holds it, days sitting, actions (forward to seller /
   return / mark fee).
3. **Chain timeline** on hop/entry detail: vertical list
   buyer2 —10k→ buyer1 —9k→ seller, with dates, proofs, per-hop status.
4. **Feed events:** hop logged, receipt confirmed/countered, chain closed
   (terminal hop saved), remainder returned / marked fee.
5. **Seller view:** seller-role user sees the plan read-only — purchase
   price, what they've received (terminal hops to them), pending in-transit
   headed their way. No visibility into buyers' internal splits.

## Worked example (partial forward)

1. Buyer2 → buyer1, 10k. Non-terminal hop, in-transit. Buyer1 gets receipt
   confirmation. Plan paid-total unchanged; in-transit +10k.
2. Buyer1 → seller, 9k, source = 9k from hop 1. Terminal. Ledger entry:
   buyer2, 9k. Paid-total +9k; in-transit drops to 1k (hop 1 outstanding).
3. The 1k later: forwarded (new terminal hop consuming it), returned
   (return hop to buyer2), or fee (ledger entry kind='fee' for buyer2).

## Testing

- Unit: outstanding math, ultimate-contributor walk (multi-level chains,
  merged sources), guard against over-consumption, terminal auto-detection.
- Service: terminal hop → correct entry fan-out (amounts, attribution,
  source_hop_id); return/fee resolutions; receipt confirm/counter
  transitions; delete/edit guards.
- API: hop CRUD permissions (plan members only; seller read-only),
  confirmation endpoints.
- UI (headless verify per repo protocol): log in-transit hop, terminal hop
  with split, in-transit panel numbers, chain timeline render.

## Migration

- Alembic: 3 new tables + `ledger_entries.source_hop_id` + seller role
  value. All additive, no backfill needed — existing entries simply have no
  chain.

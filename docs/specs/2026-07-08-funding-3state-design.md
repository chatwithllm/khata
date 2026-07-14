# Funding & Contributors 3-state breakdown

> Superseded/extended by [2026-07-14 transfer funding + FX display](2026-07-14-transfer-funding-fx-design.md).

**Date:** 2026-07-08 · **Status:** Approved · Follows payment-chains + transit-panel-v2 specs.

## Problem

Funding-sources and Contributors panels show one number ("paid to date") that hides
whether money actually reached the seller, is sitting in transit with an intermediary,
or is recorded but awaiting confirmation.

## Scope

Three states everywhere money is summarized on the asset page:

- **Delivered** — agreed ledger entries (seller has it, both parties agree).
- **Pending** — ledger entries with `amount_status != agreed` (recorded, counts toward
  paid, but attribution/amount not yet confirmed).
- **In transit** — Σ outstanding of open non-terminal hops (never in paid).

### Service

- `asset_state`: contributors rows gain `agreed_minor` + `pending_minor`
  (`paid_minor` unchanged = their sum); state gains `paid_agreed_minor` +
  `paid_pending_minor` (fees still excluded).
- `transfers.plan_transfers`: gains `in_transit_by_contributor:
  [{user_id, display, amount_minor}]` — each open hop's outstanding walked to its
  ultimate origins (same greedy oldest-first walk as terminal fan-out, starting after
  the already-consumed prefix). Non-user origins fall back to the hop logger.

### UI (asset-detail)

- **Funding sources**: headline "Delivered $X" + sub-line "· $Y in transit · $Z pending
  confirmation" (rows only when non-zero); bar gains a neutral in-transit segment.
- **Contributors**: per person, delivered amount headline; small sub-line
  "in transit $A · pending $B" when non-zero. Share % stays on paid (delivered+pending)
  as today.
- boot() fetches `/api/plans/<pid>/hops` once and passes it to both renderers.

## Non-goals

Funding-source split of in-transit money (hops carry no funding_source) — single
neutral segment. Other plan types' panels unchanged.

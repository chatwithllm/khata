# Transit Panel v2 — edit, proof attachments, restyle

**Date:** 2026-07-08 · **Status:** Approved · Follows `2026-07-08-payment-chains-design.md`

## Problem

The money-in-transit panel shipped functional but rough: unstyled rows, no way to
edit a hop after logging, and proof is a bare text ref instead of real file
attachments like ledger entries have.

## Scope

1. **Restyle** the panel to the page idiom: panel header with eyebrow + right-aligned
   in-transit KPI, ruled hop rows (ledger-style), chip badges (method chip; colored
   status chip for holding / delivered / returned / fee / receipt pending), mono
   right-aligned amounts, muted meta line, small-caps chain label, actions as small
   text links.
2. **Edit hops**: pencil action per hop (hop logger or plan owner). Small slide-over
   (log-payment pattern): amount, date, method, note; Delete inside it. Uses existing
   `PATCH /api/plans/<pid>/hops/<hid>` and `DELETE` — server guards unchanged
   (no shrink below consumed; terminal amount locked; consumed hops undeletable).
3. **Proof attachments**: real files on hops, mirroring ledger entries.
   - `attachments.hop_id` (nullable FK → transfer_hops, CASCADE) — 4th attachment
     parent. Migration `th2hopattach01` (chains from `th1hopchain01`).
   - API: `GET/POST /api/plans/<pid>/hops/<hid>/attachments` + existing
     `DELETE /api/attachments/<id>` handles the new parent.
   - Edit slide-over mounts the existing `attach.js` uploader.
   - Hop row shows a `proof` chip when `proof_ref` set or attachments exist.

## Non-goals

- No changes to chain math, fan-out, receipt flow, or resolutions.
- No hop-attachment access rules beyond the plan's existing member visibility
  (upload: hop logger or owner; view: plan members — same as entry attachments).

## Data / API deltas

- `attachments.hop_id` column; exactly one parent among entry/contact/asset_plan/hop.
- `plan_transfers()` hop rows gain `attachment_count` and include it in `has_proof`.
- New service fns mirror entry attachments (`attachments.list_for_hop`, upload path).

## Testing

- Service: attach to hop, list, delete; has_proof/attachment_count in plan_transfers.
- API: upload/list permissions (member ok, outsider 403), hop-not-found 404.
- UI: headless — panel renders styled rows, edit slide-over PATCHes, proof chip shows.

# Loans "By contact" redesign — the book of accounts

**Date:** 2026-06-19
**Branch:** `feat/loans-redesign`
**Status:** approved direction

## Problem

The By-contact loans view shipped with a hand-rolled SVG Sankey that looks broken:
blobby lozenge nodes, crossing ribbons, labels colliding with nodes. A Sankey is the
wrong tool for ~6 people × ~11 loans (a simple person→loans hierarchy, not a dense
many-to-many flow). The user dislikes it and gave UX freedom.

## Goal

Replace the Sankey + restyle the By-contact view into a clean, glanceable, editorial
layout that fits Khata's ink/ivory identity (Fraunces/Newsreader headings, mono numbers).
Show per-person exposure at a glance: principal, expected monthly interest, next-month
due, and each person's loans.

**Backend unchanged** — `GET /api/plans/loans/grouped` already returns everything
(`base_total.{lent,borrowed}`, per-group `given`/`taken` sums, `total_base_minor`, `loans`).
This is a pure `app.html` (loan view) redesign. No new endpoint, no migration.

## Research basis

- UI-skill: for proportional breakdown a **treemap** beats a Sankey; Sankey is for dense
  flows. Cards/rows beat any chart for ≤~8 entities (glanceability).
- Debt-tracker patterns (MWM IOU, Coupler.io dashboards): **dual perspective** (owed-to-you
  vs you-owe → a **net**), **per-person summary** with a proportion bar + individual totals,
  sorted by exposure, expandable to detail.

## Design

### 1. Position band (replaces the Sankey)
A single editorial summary at the top of the By-contact view:
- One slim **100%-stacked exposure meter** (one bar): green segment = **owed to you**
  (`base_total.lent.principal_minor`), red = **you owe** (`base_total.borrowed.principal_minor`).
  Labels at each end.
- Three big numbers (Fraunces / mono): **Owed to you** (green), **You owe** (red), **Net**
  (gold accent = lent − borrowed). A secondary line: next-month interest **in** (lent) and
  **out** (borrowed) from `base_total.*.interest_monthly_minor`.
- All base currency. If `data.partial`, a small "≈ excludes a currency (no FX rate)" note.

### 2. Per-contact ledger rows (the core)
A ruled list, one row per contact, sorted by `total_base_minor` desc:
- **Left:** a monogram (first initial in a small circle) + the contact **name**
  (Newsreader; a link to `/contacts/<id>` when `contact_id`, else plain) + a count chip
  (`g.given.count + g.taken.count` loans) + a tiny inline **proportion bar** = this
  contact's share of the whole book (width ∝ `total_base_minor` / max), split lent/borrowed.
- **Right:** three mono figures with labels — **principal** (net, base), **interest/mo**
  (signed +lent/−borrowed), **next due** (signed). Tabular figures, right-aligned.
- **Expand:** clicking the row (chevron) reveals the contact's loans — each a sub-row with a
  `Lent`/`Borrowed` tag, loan name (→ `/loan/<plan_id>`), and its **native** outstanding +
  native interest/mo. Smooth height transition; `prefers-reduced-motion` = instant.
- Ruled separators; gold hairline accent. Reads like a statement page.

### 3. Breakdown treemap (the "chart", replacing the Sankey visual)
A compact treemap below the position band (or collapsible): one tile per contact, **area ∝
`total_base_minor`**, tint = net direction (green if net-lent, red if net-borrowed), label =
name + outstanding (truncate small tiles to just a sliver, no label). Hand-rolled SVG/divs,
squarified-ish row layout (simple slice-and-dice is fine for ≤~10 tiles). Click a tile →
scroll to that contact's row. Hidden on very small screens (the rows already convey it).
Hand-rolled, no chart library.

### 4. Retire the Sankey
Delete `renderSankey` + its bar-fallback + related CSS. The `By direction` mode is
**unchanged**. The toggle stays.

## Accessibility / quality
- Contrast ≥4.5:1 for text; lent/borrowed never conveyed by color alone (labels + sign).
- Tabular mono figures (no layout shift). Touch targets ≥44px for the expand control.
- All names rendered via `textContent` (no innerHTML for user data) — XSS-safe.
- Treemap respects `prefers-reduced-motion` (no entrance animation); has a text/list
  equivalent (the rows). Empty state when no loans.

## Testing

No backend change → no new pytest (the endpoint + `loan_groups` are already covered). The
work is visual; verify via the headless harness per `/build-screen`:
- By-contact renders: position band (meter + 3 numbers + net), per-contact rows with the 3
  figures + proportion bars, expand reveals loans, treemap tiles present, 0 page-origin JS
  throws.
- `By direction` mode unchanged.
- The old Sankey (`renderSankey`) is gone (grep).

## Out of scope

- Backend / endpoint changes (data already sufficient).
- New chart libraries.
- Changing the `By direction` view.
- Reminders/notifications (a separate idea).

## Docs

Update `docs/specs/khata-AS-BUILT.md` change log (the By-contact view redesigned;
Sankey retired for a position band + ledger rows + treemap).

# Loans "By contact" Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementers SHOULD also invoke the `frontend-design` skill for visual quality — this is a design-quality redesign, not a mechanical change.

**Goal:** Replace the broken Sankey in the Loans "By contact" view with an editorial layout: a position band (exposure meter + owed/owe/net), ruled per-contact ledger rows (principal/interest/next-due, expandable to loans), and a compact treemap breakdown.

**Architecture:** Pure `src/khata/static/app.html` (loan view) change. The `GET /api/plans/loans/grouped` endpoint already returns all data — no backend/test/migration change. Rewrite `renderLoansByContact`; delete `renderSankey` + its bar fallback; replace the related CSS. The `By direction` mode and the toggle are untouched.

**Tech Stack:** vanilla JS + hand-rolled SVG/CSS in `app.html`; ink/ivory editorial palette (existing CSS vars).

---

## Data (already returned by `/api/plans/loans/grouped`)

```
{ base_currency, partial,
  base_total: { lent:{count,principal_minor,interest_monthly_minor,next_due_minor},
                borrowed:{...} },
  groups: [ { key, name, contact_id, total_base_minor,
              given:{count,principal_minor,interest_monthly_minor,next_due_minor},
              taken:{...},
              loans:[{plan_id,name,direction,currency,outstanding_minor,interest_monthly_minor,outstanding_base_minor}] } ]
}  // groups sorted by total_base_minor desc
```

Existing helpers in `app.html`: `el(tag,cls,text)`, `sym(ccy)` (→ ₹/$), `fmt(minor,ccy)` (grouped string with sign from value), `localStorage['loanGroupMode']`. CSS vars: `--ink`, `--ink-faint`, `--paper`, `--line`, `--line-2`, `--pos` (green), `--neg` (red), and a gold accent (grep for `--gold`/`--sindoor`; use `--gold` for "net"). `renderLoansByContact(card)` is called when mode==='contact'; `renderSankey` (lines ~669–925) is the code to delete.

Verify command (no backend change — just guards the repo): `cd /tmp/khata-loans-redesign && PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q`.

---

### Task 1: Retire Sankey + position band + ledger rows

**Files:** modify `src/khata/static/app.html`.

- [ ] **Step 1: Delete the Sankey.** Remove the entire `renderSankey(container, sankey, baseCcy, groups)` function (and its inner bar-fallback) and the call to it inside `renderLoansByContact`. Remove now-dead CSS: `.sankey-wrap`, `.sk-bar*`, `.sankey-tip`. Keep `.loan-tog` (the toggle) and `.grouped` (will be restyled).

- [ ] **Step 2: Rewrite `renderLoansByContact(card)`** to render, in order: (a) a **position band**, (b) a **treemap container** (`<div id="loan-treemap">`, filled in Task 2 — leave empty here), (c) the **ledger rows**. Money: use `sym(ccy)+fmt(minor,ccy)` for unsigned, and a signed variant for net/interest (lent +green, borrowed −red). Concrete structure:
  - **Position band:** compute `lent = base_total.lent.principal_minor`, `bor = base_total.borrowed.principal_minor`, `net = lent - bor`; a 100%-stacked meter `<div class="pos-meter">` with a green span (`flex:lent`) + red span (`flex:bor`) (guard divide-by-zero; if both 0 show a muted full bar). Three figure blocks: **Owed to you** (`lent`, green), **You owe** (`bor`, red), **Net** (`net`, gold, signed). A sub-line: next-month interest **in** `base_total.lent.interest_monthly_minor` (green) / **out** `base_total.borrowed.interest_monthly_minor` (red). If `data.partial`, append a small `.partial-note`.
  - **Ledger rows:** for each `g` in `data.groups`, a `<div class="lrow" id="grp-<slug>">` where `slug = g.key.replace(/\s+/g,'-')`. Left: a monogram circle (`g.name[0].toUpperCase()`), the name (a `<a href="/contacts/<id>">` when `g.contact_id` else `<span>`), a count chip (`(g.given.count+g.taken.count)+' loans'`), and a tiny inline proportion bar (`width = g.total_base_minor / maxTotal * 100%`, split green=given/red=taken by their principal shares). Right: three mono figure cells — **principal** = `g.given.principal_minor + g.taken.principal_minor` (unsigned), **interest/mo** = signed `g.given.interest_monthly_minor - g.taken.interest_monthly_minor`, **next due** = signed `g.given.next_due_minor - g.taken.next_due_minor`. A chevron/expand affordance.
  - **Expand:** clicking the row toggles a `.lrow-detail` block listing `g.loans` — each a sub-row: a `Lent`/`Borrowed` tag, loan name (`<a href="/loan/<plan_id>">`), native outstanding `sym(currency)+fmt(outstanding_minor,currency)` + native `interest_monthly_minor`. Animate height via a CSS class toggle; if `prefers-reduced-motion`, no transition.
  - **Empty:** `if(!data.groups.length)` render a `.emptypanel` "No loans yet." and skip the band/treemap.
  - All user text via `.textContent`/`el(...,text)` (never innerHTML) — XSS-safe. Keep the `try/catch` + `!r.ok` fetch guards from the current code.

- [ ] **Step 3: CSS.** Add editorial styles (in `app.html` `<style>`, scoped; do NOT touch app.css/ledger.css) for `.pos-band`, `.pos-meter`, `.pos-meter .seg-l/.seg-b`, `.pos-fig`, `.pos-fl/.pos-fv`, `.lrow`, `.lrow-main`, `.mono-monogram`, `.lname`, `.lchip`, `.lprop` (+ `.lprop-l/.lprop-b`), `.lfig`/`.lfl`/`.lfv`, `.lchev`, `.lrow-detail`, `.lsub`, `.ltag`. Use Fraunces/Newsreader where the page already loads them for the big numbers/names; mono (the page's existing mono stack) for figures (tabular). Gold for net. Ruled separators via `--line-2`. Keep contrast ≥4.5:1; lent/borrowed always carry a label or sign (not color-only).

- [ ] **Step 4: Verify (you).** Extract the inline `<script>` and `node --check` (clean). Run `pytest -q` (green). Grep-confirm `renderSankey` is gone. Self-review: By-direction path untouched; functions top-level; ids `grp-<slug>` present (Task 2 scrolls to them); no app.css/ledger.css edits.

- [ ] **Step 5: Commit**
```bash
cd /tmp/khata-loans-redesign
git add src/khata/static/app.html
git commit -m "feat(loans): retire Sankey; position band + per-contact ledger rows"
```

(Controller runs the live headless verify after Task 2.)

---

### Task 2: Treemap breakdown

**Files:** modify `src/khata/static/app.html`.

- [ ] **Step 1: `renderTreemap(container, groups, baseCcy)`** — a hand-rolled treemap (SVG via `createElementNS`, or positioned `<div>`s) filling `#loan-treemap`. One tile per group, **area ∝ `total_base_minor`**. Layout: a simple slice-and-dice / row-based squarify is fine for ≤~12 tiles — fit tiles into the container width (read `clientWidth`, fallback 720; height ~180px) proportional to value. Tile tint = net direction: green wash if `g.given.principal_minor >= g.taken.principal_minor` else red wash; deeper tint for larger share. Label inside (name + `sym+fmt(total_base_minor)`) when the tile is big enough (≥~64px wide AND ≥~28px tall), else no label (avoid clutter). Hover → raise tint + a tooltip (escaped) with name + amount. **Click a tile → `document.getElementById('grp-'+g.key.replace(/\s+/g,'-'))?.scrollIntoView({behavior: reduce?'auto':'smooth', block:'start'})`.**
  - Guard: empty groups → render nothing. Zero-total groups → skip the tile.
- [ ] **Step 2: Wire + responsive.** Call `renderTreemap(document.getElementById('loan-treemap'), data.groups, data.base_currency)` inside `renderLoansByContact` after the band. Hide the treemap on small screens: `if(window.matchMedia('(max-width:560px)').matches){ container.style.display='none'; return; }` at the top of `renderTreemap` (the rows convey the same info on mobile).
- [ ] **Step 3: CSS** for `.tmap`, `.tmap-tile`, `.tmap-label`, `.tmap-tip` (ink/ivory; subtle border between tiles; rounded 6px).
- [ ] **Step 4: Verify (you).** `node --check` clean; `pytest -q` green; self-review (createElementNS or divs, labels escaped, click-scroll slug matches the row id from Task 1, reduced-motion respected).
- [ ] **Step 5: Commit**
```bash
git add src/khata/static/app.html
git commit -m "feat(loans): compact treemap breakdown (area = outstanding, click to row)"
```

- [ ] **Step 6: Headless verify (controller runs).** Per `/build-screen`: start the app from this worktree on a temp DB + safe port, seed a user + several loans (2 lent "Sunil", 1 borrowed "Bank", 1 USD + an FX rate, one assigned to a real contact), log in, headless-render `/app?type=loan`, switch to **By contact**: assert 0 page-origin JS throws; **no `<svg>` sankey / no `renderSankey`**; the **position band** (meter + Owed/You owe/Net numbers) renders; **per-contact rows** with the 3 figures + proportion bars render; expanding a row reveals its loans; the **treemap** has tiles; **By direction** mode still renders the original Borrowed/Lent groups. Report concrete DOM findings + a rendered-text snapshot.

---

### Task 3: AS-BUILT doc

**Files:** modify `docs/specs/khata-AS-BUILT.md`.

- [ ] **Step 1: Update** the change log (top) — note the By-contact redesign:
```
- 2026-06-19 — Loans By-contact view redesigned. Retired the hand-rolled Sankey (unreadable
  for a small loan book) in favour of an editorial layout: a position band (100%-stacked
  exposure meter + Owed-to-you / You-owe / Net), ruled per-contact ledger rows
  (principal · interest/mo · next-due, expandable to each person's loans), and a compact
  treemap breakdown (area = outstanding, click → scroll to the contact). Frontend-only;
  same `/api/plans/loans/grouped` data. No migration.
```
Also adjust the prior 2026-06-19 "Loans grouped by contact + Sankey" §9 entry / change-log line to note the Sankey was superseded by the position-band + treemap design (one short clause, don't rewrite history).

- [ ] **Step 2: Commit**
```bash
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(loans): record By-contact redesign (position band + ledger rows + treemap)"
```

---

## Self-Review

**Spec coverage:** position band + exposure meter + owed/owe/net + next-month interest (T1) ✅; per-contact ledger rows with 3 figures + proportion bar + expand-to-loans (T1) ✅; treemap breakdown click-to-row (T2) ✅; retire Sankey (T1) ✅; By-direction unchanged + toggle kept (untouched, verified T2 step 6) ✅; XSS-safe / reduced-motion / contrast (T1/T2) ✅; docs (T3) ✅; no backend change (stated) ✅.

**Placeholder scan:** Visual styling specifics are intentionally left to the implementer + the `frontend-design` skill (this is a design-quality task); the data wiring, DOM structure, ids, money helpers, and the click-scroll slug contract are concrete. No backend code → no test placeholders.

**Type consistency:** Row id `grp-<g.key.replace(/\s+/g,'-')>` is set in T1 and used by the treemap click-scroll in T2 — same slug transform. `renderLoansByContact` consumes the documented `/loans/grouped` envelope keys (`base_total.{lent,borrowed}.{principal_minor,interest_monthly_minor,next_due_minor}`, `groups[].{key,name,contact_id,total_base_minor,given,taken,loans}`). `renderTreemap(container, groups, baseCcy)` signature consistent between definition (T2.1) and call (T2.2).

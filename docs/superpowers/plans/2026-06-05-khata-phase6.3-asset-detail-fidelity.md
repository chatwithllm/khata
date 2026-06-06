# Khata Phase 6 · Plan 6.3 — Asset-detail + Log-payment Fidelity (+ shared app shell CSS)

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`. Branch `feat/phase6-fidelity` (already checked out).

**Goal:** Rebuild `/asset/<id>` (`static/asset-detail.html`) to match `docs/mockups/asset-detail.html` — the
editorial app shell (sidebar + topbar) and the `grid2` rich panels (KPIs + progress, installment schedule
with status dots, funding-sources stacked bar, contributors sharebar) — wired to **live** data, XSS-safe,
degrading gracefully where the backend has no data. Fold in **6.2**: extract the shell CSS that 6.1 inlined
in `app.html` into a shared `static/assets/app.css` consumed by both `app.html` and `asset-detail.html`.
Restyle the log-payment modal to the mockup's slide-over aesthetic (keep the working modal pattern + the
real `POST /payments` wiring).

**Architecture:** Frontend-only. No backend/model/migration changes. Reuses existing read endpoints
(`/api/auth/me`, `/api/plans`, `/api/plans/<id>`) + `POST /api/plans/<id>/payments` + `POST /api/base-currency`
+ `sharing.js` (`mountSharing`).

---

## Data mapping (mockup element → real source — `GET /api/plans/<id>` `state` for an asset)

`asset_state`: `{total_price_minor, paid_to_date_minor, remaining_minor, overpaid_minor, next_due_seq,
installments:[{seq,planned_amount_minor,applied_minor,status∈paid/partial/due}], funding_breakdown:[{source,
amount_minor,pct}], contributors:[{user_id,display_name,paid_minor,pct}]}`.

- **Topbar:** `h1` = `plan.name`; sub = `Assets · {plan.status} · {currency}`. curtog (INR/USD → `POST
  /api/base-currency` + reload), **Log payment** button (opens slide-over), avatar (localStorage, initial =
  first letter of `display_name` from `/api/auth/me`). Auth guard: `/api/auth/me` 401 → `/`.
- **Sidebar:** same shell as `app.html`. Counts from `/api/plans` grouped by type; the **Assets** item gets
  `.on`. "New plan" → `/create`, Settings → `/settings`, Dashboard → `/app`, Holdings → `/holdings`.
- **Header KPIs (3):** Paid (`paid_to_date_minor`, `.kpi.paid`), Remaining (`remaining_minor`, `.kpi.rem`),
  Total (`total_price_minor`). The `.planhead` progress: row caption `{pct}% paid · {paidCount} of {n}
  installments` where `pct = round(paid*100/total)`, `paidCount` = count of installments with status `paid`;
  `.bigbar i` width = pct%. **Omit** the mockup's `.pace` projection block (recent-pace / projected-finish
  are NOT tracked — do not fabricate).
- **Installment schedule (`.sched`):** one `.srow` per installment. Dot class: `paid`→`.dot.paid` (✓),
  `partial`→`.dot.part` (~), `due`→`.dot.due` (seq number). `.nm` = `Installment #{seq}`. `.mt` = honest
  substitute — `paid in full` / `part-paid` / `due` (NO per-installment date/method/roll-forward badges —
  the backend does not map ledger entries to installments; omit `.rollbadge`). `.sv .pa` = `applied_minor`
  (faint when due), `.pl` = `planned {planned_amount_minor}`.
- **Funding sources (`.fund`):** from `funding_breakdown`. `.fund-amt` = `paid_to_date_minor`; `.fund-cap` =
  `funded to date · {N} source(s)`. `.stackbar i` one segment per source (width = `pct`%, cycle the mockup's
  5 colors: `--primary,--pos,--accent,--neg,--ink-faint`). `.frows` one `.fr` per source: dot color matching,
  `.nm` = source label (humanize: `chit_payout`→`Chit payout`, `sold_asset`→`Sold asset`, etc. via a small
  map + capitalize fallback — **textContent**), `.track i` width = pct%, `.amt2` = `amount_minor`, `.pct` =
  `{pct}%`. Trailing `.fr.total` row: Total paid = `paid_to_date_minor` · 100%. Empty → "No payments yet."
- **Contributors (`.contrib`):** from `contributors`. `.sharebar` one `.seg` per contributor (width = pct%,
  first `.you` palette, rest `.priya` palette; label `{display_name} {pct}%` via textContent). One `.cperson`
  per contributor: avatar initial = first letter of `display_name`, `.nm` = `display_name` (the first, if it
  is the logged-in user, prefix `You · `), `.sub` = that contributor's funding sources joined (derive by
  filtering — OR omit `.sub` if not derivable per-contributor; honest), `.rt .a` = `paid_minor`, `.l` =
  `{pct}% share`. Single contributor → still render (one full-width segment). After contributors, mount the
  **sharing/members** panel (`mountSharing(pid, box)`) as its own `.panel` so joint-ownership invites work.
- **OMIT (no backend data — honest degradation, same policy as 6.1):** the mockup's `.ledger` panel (no
  ledger-list endpoint), `.proj` sparkline/projection, `.liab` linked-liability, `.gallery` proof gallery.
  The `grid2` right rail therefore holds: Funding sources, Contributors, Members(sharing). The left column:
  KPIs+progress, Installment schedule. Use `.fillcol`/`.fill` so columns bottom-align (no blank space).
- **Currency:** reuse the mockup's `.cv[data-inr]` + `.symword` + `apply()`/`renderCV()` machinery EXACTLY as
  adapted in 6.1's `app.html` — **drop the fake `RATE=83`**; set `data-inr` from real minor÷100 and render in
  the user's real base currency (Indian grouping for INR, en-US for USD). curtog switches the real base.

## Log-payment slide-over (replaces the current `.modal`)
Restyle to the mockup's slide-over (`.scrim` + `.over` panel, eyebrow "New entry", `Log a <em>payment</em>`,
sub = `against {plan.name}` + (if `next_due_seq`) ` · #{next_due_seq} due`). Fields: **Amount** (text),
**Method** (`transfer/upi/cash/cheque` — MUST match service `METHODS`), **Funding source**
(`savings/loan/borrowed/sold_asset/chit_payout/other` — MUST match service `SOURCES`), **Note** (optional).
Save → `POST /api/plans/<id>/payments` `{amount, method, funding_source, note}`; on `ok` close + reload; on
error show `detail` via textContent (`.err`). DO NOT port the mockup's fake live-preview/carry/nextpill
math. Esc / scrim-click / Cancel closes. All built with createElement; no innerHTML on dynamic data (K4).

## Shared shell CSS (6.2 fold-in)
1. Extract the app-shell CSS that 6.1 inlined in `app.html` — everything that is **not** page-specific:
   `:root`/`html[data-cur=usd]` palettes, base/body/grain, `.mono`, `.app`,`.side`,`.brand`,`.newplan`,
   `.glyph`,`.navsec`,`.nav-i`, `.main`,`.top`,`.curtog`,`.addbtn`,`.avatar`, `.content`, `.panel`,`.ph`,
   `.tag`,`.pill`, `.grid2`,`.stack`,`.fillcol`/`.fill`/`.fillrows`/`.fillmid`, `.fade`/`[data-rise]`/reduced-
   motion — into **`src/khata/static/assets/app.css`** (verbatim values from the mockup; this is the fidelity
   backbone). Detail-page-specific blocks (`.kpis`,`.planhead`,`.sched`,`.fund`,`.stackbar`,`.frows`,`.fr`,
   `.contrib`,`.sharebar`,`.cperson`) ALSO go into `app.css` (shared across detail pages 6.4/6.5).
2. `app.html` → replace its inline shell `<style>` with `<link rel="stylesheet" href="/static/assets/app.css">`
   (keep any genuinely app.html-only rules inline if present). Its dashboard must still render identically.
3. `asset-detail.html` links `app.css` too. Slide-over (`.scrim`/`.over`) + log-payment form CSS may stay
   inline in `asset-detail.html` (page-specific) or go in app.css — implementer's call; keep it DRY.

`ledger.css` is the **landing/marketing** stylesheet — the app shell now uses `app.css`. Detail pages move
off `ledger.css` onto `app.css` (the editorial shell). Confirm fonts still preconnect/load.

---

### Task 1: Extract shared `app.css` from `app.html` (6.2)

**Files:** Create `src/khata/static/assets/app.css`; Modify `src/khata/static/app.html`; Test `tests/test_web.py`.

- [ ] Pull the shell + detail CSS (list above) out of `app.html`'s inline `<style>` into a new
  `static/assets/app.css`, verbatim. Replace the moved block in `app.html` with a `<link>` to it.
- [ ] `tests/test_web.py`: add `GET /static/assets/app.css` → 200 and contains a shell marker (e.g. `.nav-i`,
  `.curtog`). Assert `/app` still 200 and references `app.css`.
- [ ] Run `pytest tests/test_web.py -q` → green. **Done-gate:** boot live-style, load `/app` as the seeded
  demo, confirm the dashboard renders byte-for-byte as before (sidebar, topbar, stat cards, panels) — CSS
  extraction must be a no-op visually. Commit `refactor(web): extract shared app-shell CSS to app.css`.

### Task 2: Asset-detail fidelity port (wired + XSS-safe)

**Files:** Modify `src/khata/static/asset-detail.html`; Test `tests/test_web.py`.

- [ ] Rebuild `asset-detail.html` to the mockup shell + `grid2` panels per the data-mapping above, linking
  `app.css`. Keep `sharing.js` + `mountSharing`. Wire `GET /api/plans/<id>` → render KPIs/progress, schedule
  (status dots), funding stacked-bar + rows, contributors sharebar; auth guard `/api/auth/me` 401→`/`; not an
  asset → redirect `/app`. Currency machinery adapted from 6.1 (no fake RATE). Sidebar counts from `/api/plans`.
- [ ] Restyle log-payment to the slide-over; wire `POST /payments` with the **exact** METHODS/SOURCES enums.
- [ ] **K4:** every dynamic string (plan name, source/contributor labels, notes) via `textContent`/
  createElement. Only static `innerHTML=""`-style clears allowed (prefer `el.textContent=""`).
- [ ] `tests/test_web.py`: `GET /asset/1` 200 + markers (`/api/plans/`, `app.css`, `Log payment`, `curtog`,
  `Funding`, `Contributors`, `/payments`, `/api/auth/me`). 
- [ ] Run `pytest -q` (full suite — expect prior count unchanged, +new web markers). **Done-gate:** against
  the running live demo (`demo@khata.local`), open `/asset/1` → KPIs read ₹13,75,000 paid / ₹8,25,000
  remaining / ₹22,00,000 total; progress "62% paid · 5 of 8"; schedule shows 5 paid dots + 3 due; funding
  shows Savings 100%; contributors shows Demo 100%; log a ₹1 test payment then reload shows it (then it's a
  throwaway — do NOT leave it; or test on `:memory:`). Grep `asset-detail.html` for `innerHTML` → only static
  clears. Commit `feat(web): asset-detail UI fidelity — editorial shell + live panels`.

### Task 3: Docs + dashboard

- [ ] Append `docs/AGENT_LEARNINGS.md` (6.3 notes: app.css extraction; asset-detail editorial port; omitted
  ledger/projection/proof/linked-liability as honest degradation — backend lacks endpoints; log-payment
  slide-over reuses real /payments). Flip the 6.2 + 6.3 boxes in `ROADMAP.md` + update `Progress.md` (tests
  count, log line). Orchestrator owns `build_status.json`. Commit `docs: phase 6.3 progress`.

## Self-Review
CSS extraction is a visual no-op verified by the done-gate. Asset-detail gains the editorial shell + live
panels; everything rendered is real (KPIs, schedule, funding, contributors) or honestly omitted (ledger,
projection, proof, linked-liability). Log-payment keeps the working endpoint with the slide-over skin and
correct enums. XSS-safe throughout. No backend changes. ✓

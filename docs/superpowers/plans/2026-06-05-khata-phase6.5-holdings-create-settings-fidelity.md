# Khata Phase 6 · Plan 6.5 — Holdings + Create + Settings + Analysis Fidelity (Phase 6 finale)

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. Do NOT touch `build_status.json`, `khata_live.db*`, `.env.live`, `OD_khata_mockup/`. Branch `feat/phase6-fidelity`. Stage files explicitly (never `git add -A`).

**Goal:** Bring the remaining app pages to editorial fidelity on the shared `app.css` shell: port
`holdings.html` (→ `docs/mockups/holdings.html`) and `create-plan.html` (→ `docs/mockups/create-plan.html`)
to mockup composition wired live; give `holding-detail.html`, `settings.html`, `analysis.html` the same
editorial shell for consistency (no dedicated mockups — follow the established pattern); and **restore the
chit auction-what-if calculator** (`GET /chit/dividend`) dropped in 6.4 as a compact slide-over. After this,
Phase 6 is complete → open the PR for `feat/phase6-fidelity`.

**Architecture:** Frontend-only. Reuse existing endpoints. No backend/migration changes. Same proven recipe
as 6.1/6.3/6.4 (app.css shell, currency machinery without fake RATE, K4 createElement+textContent, honest
degradation).

## Shared recipe (every page)
Link `/static/assets/app.css`; mockup `.app` sidebar + `.main` topbar + `.content`. Auth guard `/api/auth/me`
401→`/`. Sidebar counts from `/api/plans` (the active page's nav item `.on`). Currency machinery from
app.html (no RATE; real base currency, Indian INR / en-US USD; curtog → `POST /api/base-currency` + reload).
All dynamic strings via textContent. Honest degradation: render only what endpoints expose.

---

### Task 1: Holdings + net worth fidelity (`/holdings`)

**Files:** Modify `src/khata/static/holdings.html`; Test `tests/test_web.py`. Read first:
`docs/mockups/holdings.html`, current `src/khata/static/holdings.html`, `src/khata/services/networth.py` (the
`/api/networth` shape), `src/khata/api/feed.py` (`/api/feed/config`).

`GET /api/networth` → `{base_currency, assets_minor, liabilities_minor, net_worth_minor, holdings:[{id, name,
asset_class, qty_held_micro, current_value_minor, unrealized_gain_minor, priced(bool), value_in_base_minor|
null, currency}], unpriced:[...], unconverted:{ccy:{assets_minor,liabilities_minor}}}`.

Panels (editorial shell):
- **Net worth panel** (hero): `.kpis` Assets (`assets_minor`) / Liabilities (`liabilities_minor`) / Net worth
  (`net_worth_minor`). The mockup's "Assets − Liabilities = Net" breakdown row — real.
- **Holdings table panel:** one row per holding — name (textContent) + `asset_class`, `qty_held_micro` (÷1e6),
  `current_value_minor`, `unrealized_gain_minor` (color by sign), `value_in_base_minor` (or a "no rate" /
  "unpriced" flag when null), and an inline **quote** input (Enter → `POST /api/plans/<id>/holding/quote
  {price}`) — keep the working manual-quote UX. Link each row → `/holding/<id>`.
- **Spot-prices / live-feed:** the mockup's "Live spot prices" strip is decorative market data we do NOT have.
  Gate on `GET /api/feed/config.enabled`: if disabled (default), OMIT the spot strip (show "manual quotes" copy
  or nothing) — do NOT fabricate ticker prices. If enabled, a per-row "refresh (live)" affordance may post
  `/holding/refresh-quote` (mirrors holding-detail). Default path: manual only.
- **Currency / FX controls:** base-currency select → `POST /api/base-currency`; FX rate (quote+rate) → `POST
  /api/fx-rates` (keep current working controls; restyle into the shell). Callout for `unpriced` / `unconverted`
  (honest, from real payload).
- `tests/test_web.py`: `/holdings` 200 + markers (`/api/networth`, `app.css`, `curtog` or base control,
  `/holding/quote`, `/api/auth/me`). Done-gate: live `/api/networth` (gold holding 92.5g @ ₹6,450) renders the
  table + net worth; grep innerHTML → only static clears. Commit `feat(web): holdings UI fidelity — editorial shell + live net worth`.

### Task 2: Create-plan fidelity (`/create`)

**Files:** Modify `src/khata/static/create-plan.html`; Test `tests/test_web.py`. Read first:
`docs/mockups/create-plan.html`, current `src/khata/static/create-plan.html`, `src/khata/api/plans.py`
`create()` (the per-type payload keys + enums — asset/loan/holding/chit/retirement).

Port the mockup's tabbed editorial form on the app.css shell. Tabs: **asset / loan / holding / chit /
retirement** (the current page may only have 3 — ADD chit + retirement so all five plan types are creatable,
matching the backend). Per-tab fields → the EXACT `create()` payload keys + enum values:
- asset: name, total_price, installments builder (seq, amount, due_date).
- loan: name, direction (`given`/`taken`), counterparty, interest_type (`none`/`monthly`/`yearly`), rate,
  start_date, tenure_months.
- holding: name, asset_class, unit, symbol, purity.
- chit: name, chit_value, n_members, commission, start_date.
- retirement: name, current_age, retirement_age, current_balance, monthly_contribution, employer_match,
  annual_return, inflation.
- currency select (INR/USD) on all. POST `/api/plans`; on 201 → redirect to the new plan's detail route
  (`/asset|loan|holding|chit|retirement/<id>`); on error → `.err` textContent.
- `tests/test_web.py`: `/create` 200 + markers (`/api/plans`, `app.css`, `asset`, `chit`, `retirement`,
  `/api/auth/me`). Done-gate: each of the 5 tabs builds a valid payload (verify field keys against `create()`).
  grep innerHTML. Commit `feat(web): create-plan UI fidelity — all five plan types on the editorial shell`.

### Task 3: Holding-detail + Settings + Analysis shell + restore chit calculator

**Files:** Modify `src/khata/static/holding-detail.html`, `settings.html`, `analysis.html`,
`chit-detail.html`; Test `tests/test_web.py`.

- **holding-detail.html:** apply the editorial shell (app.css sidebar+topbar) + panels (position: qty, avg
  cost, current value, unrealized/realized gain from `holding_state`; buys/sells/quote actions; the
  feed-gated "Refresh (live)" button already there — keep). Keep `mountSharing`. Same recipe.
- **settings.html:** editorial shell; sections Profile (display_name → `/api/auth/profile`), Password
  (set/change → `/api/auth/password`, "set" vs "change" by `has_password`), Currency (base → `/api/base-currency`,
  FX → `/api/fx-rates`). Keep auth guard + per-section textContent feedback.
- **analysis.html:** editorial shell; the hold-vs-sell tool (`/api/analysis/...` — read current page for the
  endpoint) restyled into a panel.
- **chit-detail.html:** RESTORE the auction-what-if calculator as a compact slide-over (or panel): inputs the
  winning bid → `GET /api/plans/<id>/chit/dividend?bid=<amount>` → show per-member dividend + net subscription.
  This re-homes the live `/chit/dividend` endpoint (orphaned in 6.4). createElement/textContent; honest.
- `tests/test_web.py`: keep `/holding/1`, `/settings`, `/analysis` 200 + `app.css` markers; `/chit/1` gains a
  `/chit/dividend` marker again. Done-gate: pages serve; settings password set/change wired; analysis computes;
  chit calculator returns dividends from the live endpoint. grep innerHTML across all four. Commit
  `feat(web): holding-detail/settings/analysis shell + restore chit auction calculator`.

### Task 4: Review, docs, Phase 6 completion + PR
- Dispatch a reviewer over Tasks 1–3 (spec + K1/K4/K5 + no fabrication + tests green).
- Append `docs/AGENT_LEARNINGS.md` (6.5 notes). Flip 6.5 box + mark **Phase 6 COMPLETE** in `ROADMAP.md` +
  `Progress.md`. Orchestrator updates `build_status.json` (17/17). Commit `docs: phase 6.5 — Phase 6 complete`.
- Run the FULL suite green. Then **finishing-a-development-branch**: push `feat/phase6-fidelity` + open PR
  (title "Phase 6 — UI fidelity (mockup-faithful app, wired to live data)"; body summarizing 6.1–6.5; footer
  🤖 Generated with Claude Code). Do NOT merge automatically — leave the PR for review (consistent with prior phases).

## Self-Review
Holdings + create-plan reach mockup fidelity; holding-detail/settings/analysis gain shell consistency; the
chit calculator is restored (no orphaned endpoint). All five plan types creatable. Live-feed spot strip gated
on real feed config (no fabricated tickers). XSS-safe; honest degradation; no backend changes. Phase 6 done. ✓

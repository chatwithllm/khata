# Khata — As-Built Spec (rebuild blueprint)

**Purpose:** single source of truth to rebuild Khata from scratch without reading the running app.
Pairs with the *intent brief* (`2026-06-04-khata-design.md` = the why/vision); **this doc = the what/how-built.**
Update this doc on every change (see "Change log" at the bottom).

Last synced to code: 2026-06-05 (branch `feat/landing-page`).

---

## 1. What it is
Privacy-first, **self-hosted** personal money-plans ledger. Flask + SQLite, **static HTML pages + JSON
APIs** (no server-side templating; vanilla-JS client render). Tracks asset purchases (installments),
loans (given/taken, secured), holdings + net worth, chit funds, and a retirement planner — as **one honest
ledger** with proof, multi-currency (INR/USD), and multi-user contribution sharing.

## 2. Non-negotiable money rules (the spine)
- **Money = integer minor units** (×100). **Quantities = integer micro units** (×10⁶). **Rates = basis
  points** (bps, ×100) or **rate_micro** (×10⁶ for FX). **Never float for money/qty/rate.**
- All money arithmetic via `Decimal` + `ROUND_HALF_UP`.
- **Balances are DERIVED, never stored** — every `*_state()` recomputes from `ledger_entries`. The ledger
  is the only source of truth.
- **Original amount/currency immutable** per plan; one ledger distinguished by `kind`/`direction`.
- Parsers reject junk → `ValueError` → API returns **400, never 500** (`to_minor`/`to_micro`/`pct_to_bps`).

## 3. Tech stack & layout
- Python 3.12, **Flask 3.1**, **SQLAlchemy 2.0** (typed `Mapped`/`mapped_column`), **Alembic** (batch mode,
  `render_as_batch=True`), pytest. SQLite file DB.
- `src/khata/`: `models/` · `services/` (domain logic, returns plain dicts) · `api/` (Flask blueprints,
  JSON) · `web.py` (serves static pages) · `static/` (HTML/CSS/JS) · `money.py` · `config.py` · `db.py`.
- App factory: `create_app(cfg)`. Config from env: `KHATA_SECRET_KEY`, `KHATA_DATABASE_URL`,
  `KHATA_ENV`, `KHATA_GOOGLE_CLIENT_ID` (optional), `KHATA_PRICE_FEED` (optional).
- Frontend rule **K4 (XSS):** all dynamic DOM via `createElement` + `textContent`; **never** `innerHTML`
  on user/API data. Pages: `ledger.css` (landing/marketing, `.landing`-scoped animations) + `app.css`
  (app shell + detail panels); `sharing.js` (`mountSharing`). HTML served `Cache-Control: no-store`.

## 4. Data model (11 tables)
- **users**: id, email, display_name, password_hash?, google_sub?, base_currency, created_at.
- **plans** (spine): id, owner_user_id, **type** (asset|loan|holding|chit|retirement), name, currency,
  status, created_at. 1:1 → asset/loan/holding/chit/retirement; 1:N → installments, ledger_entries,
  memberships.
- **asset_purchases**: plan_id, total_price_minor.
- **installments**: id, plan_id, seq, planned_amount_minor, due_date?, note?.
- **loans**: plan_id, direction (given|taken), counterparty?, interest_type (none|monthly|yearly),
  rate_bps, basis, repayment, start_date, tenure_months?, secured (bool), collateral_plan_id? (FK→plans).
- **holdings**: plan_id, asset_class, unit, symbol?, purity?, current_price_minor?, price_as_of?.
- **chits**: plan_id, chit_value_minor, n_members, commission_bps, start_date.
- **retirements**: plan_id, current_balance_minor, monthly_contribution_minor, employer_match_bps,
  annual_return_bps, inflation_bps, current_age, retirement_age.
- **ledger_entries** (the heart): id, plan_id, logged_by_user_id, **direction** (in|out), **kind**?,
  amount_minor, quantity_micro?, currency, **occurred_at** (when it happened), method?, funding_source?,
  proof_ref?, note?, **created_at** (when it was logged). Editable in place (see §7).
- **plan_memberships**: id, plan_id, user_id, role (owner|contributor|…), created_at.
- **fx_rates**: id, base_currency, quote_currency, rate_micro, as_of?.

## 5. Enums (authoritative)
- currencies `{INR, USD}` · payment methods `{cash, upi, transfer, cheque}` · funding sources
  `{savings, loan, borrowed, sold_asset, chit_payout, other}` · loan direction `{given, taken}` ·
  interest_type `{none, monthly, yearly}` · loan entry kinds `{interest_payment, principal_repayment}`
  (+ `disbursement` via its own endpoint) · asset_class `{gold, silver, equity, mf, cash, other}` ·
  chit kinds `{chit_contribution, chit_dividend, chit_prize}`.

## 6. Derived state contracts (what `GET /api/plans/<id>` returns as `state`, by type)
- **asset_state**: total_price_minor, paid_to_date_minor, remaining_minor, overpaid_minor, next_due_seq,
  installments[{seq, planned_amount_minor, applied_minor, status(paid|partial|due)}], funding_breakdown
  [{source, amount_minor, pct}], contributors[{user_id, display_name, paid_minor, pct}], **ledger**
  [{id, kind, direction, amount_minor, created_at, occurred_at, method, funding_source, note, has_proof}].
- **loan_state**: direction, currency, principal_outstanding_minor, interest_accrued_minor,
  interest_paid_minor, interest_due_minor, total_minor, as_of, schedule[{month_index, period_start,
  expected_minor, applied_minor, status}], next_due_month, months_behind, secured, collateral|null
  {plan_id, name, asset_class, currency, value_minor, ltv_pct}, **ledger** [same shape as asset].
- **holding_state**: asset_class, unit, symbol, purity, currency, qty_held_micro, avg_cost_per_unit_minor,
  cost_of_held_minor, current_price_minor, price_as_of, current_value_minor, unrealized_gain_minor,
  realized_gain_minor, proceeds_minor.
- **chit_state**: currency, chit_value_minor, n_members, commission_bps, subscription_minor,
  total_contributed_minor, total_dividends_minor, prize_received_minor, net_contributed_minor,
  net_position_minor, won, months_recorded, ledger[{id?, kind, direction, amount_minor, occurred_at, note}].
- **retirement_state**: currency, current_balance_minor, monthly_contribution_minor, employer_match_bps,
  annual_return_bps, inflation_bps, current_age, retirement_age, months_to_retirement,
  effective_monthly_minor, total_contributions_minor, projected_corpus_minor, projected_corpus_real_minor.

## 7. API surface (all endpoints)
**Auth** (`/api/auth/*`): POST register · login · logout · google · password · profile · GET config
(`{google_client_id}`) · me (`{user:{id,email,display_name,has_password}}`).
**Plans** (`/api/plans*`): GET `""` (list) · GET `/<id>` (`{plan, state}`) · POST `""` (create, dispatches
on `type`) · POST `/<id>/installments` · POST `/<id>/payments` (asset; accepts **occurred_at**) ·
**PATCH `/<id>/entries/<entry_id>`** (edit a ledger entry — owner-only; amount/occurred_at/method/
funding_source/note; recomputes derived state) · POST `/<id>/loan/disbursements` · POST `/<id>/loan/entries`
· POST `/<id>/loan/collateral` · POST `/<id>/holding/buys|sells|quote|refresh-quote` · POST
`/<id>/chit/entries` · GET `/<id>/chit/dividend?bid=` · POST `/<id>/retirement/update` · GET/POST
`/<id>/members` · DELETE `/<id>/members/<user_id>`.
**Net worth / FX** (`/api`): GET networth · GET dashboard (`{net_position_minor, paid_to_date_minor,
i_owe_minor, owed_to_me_minor, plans:[{id,type,name,currency,role}]}`) · POST base-currency · POST fx-rates.
**Analysis**: GET `/api/analysis/hold-vs-sell?asset_value&appreciation&borrow&interest&horizon`.
**Feed** (optional): GET `/api/feed/config` (`{enabled}`).

**Authorization:** mutations are **owner-only** (`_owned_plan`); reads are owner-or-shared
(`_accessible_plan`). Unauthenticated → 401; not found → 404; not yours → 403. Pattern: validate → mutate →
`commit` on success / `rollback` on error.

## 8. Pages / routes (static, client-rendered; auth guard `/api/auth/me` 401→`/`)
`/` landing (marketing + embedded sign-in modal) · `/features` · `/app` dashboard (sidebar, stat cards,
plan panels, Lent panel, chit badges) · `/create` (4-step wizard modal, all 5 types) · `/holdings`
(net worth + table + hold-vs-sell) · `/asset/<id>` (KPIs, schedule, **ledger w/ edit**, funding,
contributors, log-payment slide-over w/ **date**) · `/loan/<id>` (at-a-glance, release schedule, ledger,
collateral when secured) · `/chit/<id>` (stats, rounds table, ledger) · `/holding/<id>` · `/retirement/<id>`
(NPS projector) · `/settings` · `/analysis`.

## 9. Enhancements beyond the intent brief (record new ones here)
- **2026-06-05 — Editable ledger.** `PATCH /api/plans/<id>/entries/<entry_id>` (owner-only) edits an
  existing entry's amount/occurred_at/method/funding_source/note; `kind`/`direction` immutable; derived
  balances recompute. Frontend: ✎ edit on each asset-detail ledger row reopens the slide-over pre-filled.
- **2026-06-05 — Payment date.** Log-payment slide-over has a "Date (when it happened)" field → `occurred_at`
  (distinct from auto `created_at` = when logged). Ledger shows "· logged X" when the two differ.
- **2026-06-05 — `ledger` exposed in asset/loan state** (was chit-only); entries carry `id` + `created_at`.

## 10. Deviations / deferred vs the intent brief (so a rebuild knows what's NOT there)
- **Retirement** built as **INR NPS compound projector**, not the brief's **US 401(k)** (IRS limits,
  paycheck deferral, employer match, true-up). US 401(k) = new plan type + model — not built.
- **Loan EMI/bullet** comparison + amortization — not built (needs a compute endpoint).
- **Roll-forward installments** — partial: greedy fill + derived "short ₹X" badge; no preserved-original.
- **Collateral** — holding-reference + derived LTV only; no standalone records / type / lender / LTV-cap /
  pledge→release lifecycle.
- **Hold-vs-sell** — numbers + verdict; appreciation-vs-interest crossover chart partial.
- **Live market prices** — optional seam only (manual quotes); no real provider wired.
- **Explicitly future:** OCR receipt autofill · native mobile app.

## 11. Run / deploy (local, self-hosted)
- Entry: `wsgi.py` (root) or `create_app().run(...)`. Production-ish: `KHATA_ENV=production`, `debug=False`,
  `host=0.0.0.0`, a real `KHATA_SECRET_KEY`, persistent `KHATA_DATABASE_URL=sqlite:///<file>.db`.
- Schema: `alembic upgrade head` (single linear head). Migrations: batch mode; `server_default` for new
  NOT NULL on existing tables; round-trip verified.
- **Canonical local instance** (current): port **5057**, code from the `feat/landing-page` worktree,
  data in `khata_app.db`, secret persisted in `.env.app`, restart via `run-app.sh`. HTML is `no-store`
  (always fresh); static edits live on reload; Python edits need a restart. **Not yet** a reboot-surviving
  service (launchd) — add when wanted. Back up `khata_app.db` (only source of truth).

## 12. Process going forward
**Every enhancement updates this doc** (§9 + the change log) in the same commit as the code — so a
from-scratch build reads here, not the app. Verify UI changes with the headless harness
(jsdom render + raw-HTML/CSS/mockup diff) before "done".

---

## Change log
- 2026-06-05 — Created this as-built spec. Recorded: editable ledger (PATCH /entries), payment occurred_at
  vs created_at, ledger exposure in asset/loan state, single-port deploy (:5057). Full app on
  `feat/landing-page` (PR #14); roadmap Phases 1–6 done; deviations/deferrals in §10.

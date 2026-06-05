# Khata — Agent Learnings

Append-only log. Each entry: date · what happened · the rule it produced (if any).

## 2026-06-04
- Project scaffolded; chose integer-minor-units for money and derived balances as
  locked rules before writing any money code. → see agent-rules #2, #3.
- Host had no Python 3.11; built on Python 3.12 instead. All pinned deps
  (Flask 3.1, SQLAlchemy 2.0.36, Alembic 1.14, Werkzeug 3.1.3) install clean. → no
  rule; record the runtime so future migrations match.
- SQLite `:memory:` test DBs work across request-scoped sessions because SQLAlchemy
  uses a SingletonThreadPool (one connection per thread) — tables created on the
  engine persist for the test client's sessions. → if we ever move tests to a
  thread pool / multiple threads, switch to `StaticPool` or a temp-file DB.
- `alembic/env.py` self-adds `src/` to `sys.path` and reads `KHATA_DATABASE_URL`,
  so migrations run without exporting PYTHONPATH. → keep env.py self-contained.

## 2026-06-04 — Plan 2 (plan/ledger spine + Asset purchase)
- Roll-forward modeled as **greedy cumulative application** of total paid across the ordered
  schedule (money is fungible), not payment→installment tagging. Fully derived from the ledger;
  matches the single-source-of-truth rule and is simpler. Only `direction="out"` entries count.
- **Bug the plan's draft missed (subagent caught it):** `set_installments` must validate amounts
  BEFORE deleting old rows, and must `session.expire(plan, ["installments"])` + append to the
  relationship collection (not bare `session.add`) so the schedule reads back in the same
  `autoflush=False` session. → when "replacing" a child collection, drive it through the
  relationship + expire, and validate before mutating.
- `money.to_minor` now rejects `float` (TypeError) and non-finite values — enforces rule #2
  ("money is never float") at the input boundary, not just by convention.
- Security guards (401 unauth on every endpoint; 403 non-owner on every plan-scoped endpoint)
  have explicit tests, so a future refactor that drops a guard fails CI. → never ship a
  plan-scoped endpoint without an ownership test.
- Funding-breakdown pcts are rounded independently and may not sum to exactly 100 (display only).
- A reviewer flagged a `single_parent=True` SAWarning on the 1:1 delete-orphan relationship;
  verified it does NOT occur in SQLAlchemy 2.0.36 (`pytest -W error::SAWarning` passes) → not applied.
- Final review caught: the float guard means `to_minor` raises `TypeError`, so the API must catch
  `TypeError` too (a JSON number must yield 400, not 500); fixed. Also added service-level currency
  validation (don't rely on the API's `to_minor`) and tz-normalize naive `occurred_at` to UTC.

### Deferred follow-ups (do when touched / in Plan 3)
- `_detail`/state is asset-specific (`asset_state` reads `plan.asset`, treats `out` as purchase
  payments). Plan 3 (Loan) needs a `plan.type` dispatch → `loan_state` (disbursement is `in`,
  repayments `out`). Consider a generic `create_plan` service factory too.
- Add a DB `CHECK (type IN (...))` on `plans.type` and a `UniqueConstraint(plan_id, seq)` on
  `installments` when a new migration is next written (API already enforces replace semantics).
- DRY: `_utcnow` is duplicated in `user.py`/`plan.py`/`ledger.py` — extract when convenient.
- `_summary` returns `total_price_minor=None` for an asset-less plan while `asset_state` returns 0 —
  reconcile once non-asset plan types exist.

## 2026-06-04 — Plan 3 (Loan)
- Loan movements reuse `ledger_entries` via a `kind` column (disbursement / interest_payment /
  principal_repayment); `method`/`funding_source` made nullable. SQLite can't drop NOT NULL in
  place → `render_as_batch=True` in `alembic/env.py` so the migration recreates the table; alembic
  autogenerate then emitted the batch `alter_column` calls itself.
- Interest is derived (reducing-balance, simple, whole-month) with `Decimal` over integer minor
  units; rates stored as integer basis points (`pct_to_bps`) — no float anywhere. Verified
  end-to-end: 8.5%/yr on ₹6L for 4 complete months = ₹17,000 accrued.
- `direction` (in/out) is set from (loan.direction, kind) for cashflow display; loan math uses
  `kind`+amount magnitudes only.
- Review caught: `principal_outstanding` must gate by `as_of` like the schedule does (else a
  future-dated disbursement inflates the as-of balance). Fixed. Added an end-of-month start_date
  test to lock the `_month_add` day-clamping (Jan-31 → Feb-28 period starts).
- The Plan-2 `_detail`/`create` now dispatch on `plan.type` (asset|loan) — the follow-up flagged
  in Plan 2 is done. `_parse_dt` (tz-normalize) is now shared by the asset payment + loan endpoints.

### Deferred follow-ups (Plan 3 final review — non-blocking)
- Both `asset_state` and `loan_state` take a `session` arg they don't use (they read via loaded
  relationships). Kept for symmetry; reconcile both at once later (drop the arg, or query fresh).
- `loan_state` `as_of` is hardcoded to `date.today()` in the API; the service supports any `as_of` —
  expose it when an "as-of" report/audit view is needed.
- Index `ledger_entries (plan_id, kind)` if/when state functions move to explicit SELECTs (currently
  O(n) Python filter over the relationship — fine at personal-finance scale).
- A long loan's `schedule` is unbounded (360 rows for 30y); page/cap it when a dashboard needs it.
- `list_plans` isn't type-filtered (reused for asset+loan); add a `type` filter in Plan 4.
- The loans migration `downgrade` restores `method`/`funding_source` to NOT NULL — would fail on
  Postgres if loan entries (method=NULL) exist; one-way in practice, flag before prod downgrades.

## 2026-06-04 — Plan 4 (Sharing & contributors)
- `PlanMembership` (contributors only); owner stays `plans.owner_user_id`. API access split:
  `_accessible_plan` (owner-or-member) for reads + asset payments; `_owned_plan` (owner-only) for
  installments / loan endpoints / membership management. Members' payments self-attribute via
  `logged_by_user_id=user.id`.
- Ownership share is derived: `asset_state` groups `out` entries by `logged_by_user_id` →
  `contributors[{user_id, display_name, paid_minor, pct}]` (resolves the unused-`session` note for
  asset_state). `loan_state` still takes an unused session — reconcile both later.
- `dashboard.net_position` rolls up only the user's OWNED loans for i_owe/owed_to_me, and asset
  `out`-payments the user logged for paid_to_date (so shared-asset contributions count per-user).
- Review-driven cleanup: `api.plans.index` and `dashboard.net_position` had duplicated owned+member
  resolution; extracted `sharing.user_plans(session, user_id) -> (owned, member)` (newest-first,
  deduped) used by both. Dropped an always-true `assert ... or True` scaffold line in a dashboard test.

## 2026-06-04 — Plan 5 (Google sign-in + Features page)
- Google sign-in is identity-only via GIS ID tokens. The verifier (`verify_google_credential`,
  google-auth) is **injected** through `app.config["GOOGLE_VERIFIER"]` and imports google-auth
  lazily, so all auth logic is unit-tested with plain claims dicts — no network, no real client ID.
- `login_with_google` is find-by-`google_sub` → link-by-verified-email → create. Linking/creation is
  gated on `email_verified` (raises `EmailUnverifiedError` → 403). `google_sub` is unique; matching by
  sub first means a changed Google email never forks the account. Review-fix: refuse to link when the
  email-matched account already has a *different* google_sub (`GoogleAuthError("account_link_conflict")`,
  maps to 401) — prevents silently overwriting an existing Google identity.
- API split: `GET /api/auth/config` exposes the (public) client id so a fully static frontend can
  decide whether to render the Google button; `POST /api/auth/google` 503s when unconfigured — so
  self-hosters who skip OAuth still get working email/password.
- Frontend now has a real shared stylesheet `static/assets/ledger.css` (extracted verbatim from the
  mockup kit §2) used by both static pages — the first step toward building the real app UI off the
  mockups. The landing login JS sets all error text via textContent (XSS-safe) and never loads GIS
  unless a client id is configured.

### Deferred follow-ups
- Let Google-created users (password_hash=NULL) set a password later (account settings).
- Import Google profile picture (we already support manual upload; left out per YAGNI).
- The landing/login page is hand-rolled HTML+JS; when the real app shell is built, consolidate the
  auth JS into a shared module. Remove the unused `#g_id_onload` div.
- `verify_google_credential` catches only ValueError; a google-auth TransportError (Google
  unreachable during cert fetch) currently propagates as 500 — acceptable (not the user's token), note
  before prod.

## 2026-06-04 — Plan 2A (Holdings foundation)
- New `holding` plan type via the generic-position model: one `holdings` detail row
  (asset_class/unit/symbol/purity + manual `current_price_minor`/`price_as_of`) per plan; buys/sells
  are `ledger_entries` rows (`kind='buy'/'sell'`) carrying the new nullable `quantity_micro`.
- **Quantities are integer micro-units (×10⁶)** — `money.to_micro`/`format_micro`, rejecting float the
  same way `to_minor` does. Valuation uses `Decimal` over integer minor/micro units; no float anywhere.
- `holding_state` derives everything (average-cost basis): qty held, avg cost/unit (minor per WHOLE
  unit), cost of held, realized gain (proceeds − avg×sold), and — only when a quote is set — current
  value + unrealized gain (else both null). Oversell (selling more than held) is rejected in `add_sell`.
- Holding buy/sell append through `plan.ledger_entries` (not bare `session.add`) so a freshly-loaded
  collection stays consistent when `holding_state` is read between mutations — avoids the stale-
  collection class of bug seen in Plan 2's `set_installments`.
- API extends the existing `type`-dispatch (asset|loan|holding) for create + detail; the three holding
  mutations are owner-only. Dashboard/net_position deliberately untouched — that's Plan 2B.
- Review caught: the avg-cost convention is minor-units-per-WHOLE-unit (e.g. ₹52,000/g = 5_200_000),
  not per-micro — a plan-draft test constant was off by ×100 and was corrected. Also fixed a quote
  test that mixed price scales (₹50,000/g cost vs a ₹600/g quote) to assert a sensible positive gain.

### Deferred follow-ups (Plan 2B / later)
- `add_buy`/`add_sell` raise `TypeError` (not `ValidationError`) on `quantity_micro=None`; harmless
  end-to-end (the API catches `TypeError`→400 and `to_micro("")` rejects empty first), but add a
  `None` guard in `_add_entry` for service-level consistency.
- Add edge tests: sell-to-zero then re-value, multiple sequential sells, quote=0, and None/0 quantity
  rejected with `ValidationError`.
- Roll holdings' `current_value_minor` into `dashboard.net_position` gross assets; cross-currency FX.
- Build the rich `holdings.html` net-worth UI. Price history + live spot feeds. Dividends/401(k).
- `holding_state`/`asset_state`/`loan_state` all take an unused `session` arg — reconcile together.

## 2026-06-04 — Plan 2B (Net-worth consolidation + cross-currency)
- `User.base_currency` (default INR) + a global `fx_rates` table (directed `(base,quote)` →
  `rate_micro`, base units per 1 quote unit ×10⁶). `services/fx.py`: `convert` (exact Decimal),
  `get_rate` (identity for base==quote, None on miss), `set_rate` (upsert, validates pair + positivity).
- `services/networth.net_worth` consolidates OWNED plans only: holdings at market `current_value`
  (asset), loan given = asset, loan taken = liability; asset-purchase plans excluded. Each valued
  amount is converted to base if a rate exists, else added to an `unconverted[ccy]` bucket. Unquoted
  holdings → `unpriced[]`. Nothing guessed (the "value-what-you-can" rule). The money-flow invariant —
  base totals can never include unconverted/unpriced — is enforced structurally (one `_apply` helper).
- New `networth` blueprint hosts `/api/networth` + `/api/base-currency` + `/api/fx-rates` (the FX rate
  is set from the caller's current base to a quote; parsed via `to_micro`, so float is rejected).
- `holdings.html` at `/holdings` renders the live consolidation (assets/liabilities/net, unpriced +
  unconverted callouts, per-holding inline quote). Review + the automated security scan caught a
  stored-XSS in the row rendering (holding name/asset_class via innerHTML) — fixed to build cells via
  createElement + textContent. Lesson: never innerHTML user-controlled strings; the editorial pages'
  static markup is fine, but any list rendered from API data must use DOM/textContent.
- The existing `/api/dashboard` (`net_position`) was deliberately left untouched — net worth is a
  separate, holdings-aware endpoint.

### Deferred follow-ups
- Gold-loan-vs-selling analysis; live spot/FX feeds; holdings in shared plans; asset-purchase net-worth
  treatment; fold net worth into the main dashboard.
- `net_worth`/`*_state` use `as_of=date.today()` (non-deterministic across day boundaries) and take an
  unused `session` arg in places — reconcile when an as-of report view is built.
- Add a null guard to `fmtMicro` in holdings.html (symmetry with fmtMinor). Carry the 2A follow-ups
  (None-qty ValidationError guard, holdings edge tests).

## 2026-06-04 — Plan 3.1 (App shell + dashboard)
- Real `/app` shell replaces the placeholder: sidebar + topbar + dashboard cards + a client-side
  type-filterable plan list, all wired to the existing read APIs (`/api/auth/me`, `/api/networth`,
  `/api/dashboard`, `/api/plans`). No backend changes — Phase 3 is wiring mockups to built APIs.
- Auth guard is client-side (`GET /api/auth/me`, 401→`/`), consistent with the static-page pattern;
  pages stay static, no server templating. Parallel `Promise.all` fetch for the three dashboards.
- All dynamic rows are built with `createElement`+`textContent` (XSS-safe) per the Plan-2B lesson.
- App-shell CSS (sidebar/topbar/cards/rows) lives inline in `app.html`; tokens + grain come from
  `ledger.css`. When 3.2–3.5 add more app pages, consider promoting the shell CSS into a shared sheet.
- The "New plan" button + plan-row detail links point at routes that Plans 3.2–3.5 add; informational
  rows for now (clickable detail lands with the detail pages).
- Follow-up (Phase 5.2): the dashboard fetches have no non-401 error handling — a rejected fetch leaves
  cards at "—" and rejects Promise.all silently. Add error UI in the hardening sweep.

## 2026-06-04 — Plan 3.2 (Create-plan flow)
- `/create` page: one tabbed form (asset/loan/holding) that builds the exact JSON shape each type needs
  and posts to `POST /api/plans`, redirecting to `/app`. Auth-guarded client-side; installments add/remove
  builder; rate field reveals only for interest≠none. No backend change. Error `{detail|error}` via
  textContent; all dynamic rows via createElement (K4). Contract pre-flighted against `api/plans.py` (K5).
- Now under the web-app-builder harness: `agent-rules.md` (K1–K8) is binding for every task; done-gate
  requires a real end-to-end verification (booted the app, created all 3 types → 201), not just a green
  test. `build_status.json` is the live dashboard feed (orchestrator-owned).

## 2026-06-04 — Plan 3.3 (Asset detail + log-payment)
- `/asset/<id>` page (id from `location.pathname`): total/paid/remaining cards, schedule with status
  badges, funding bars, contributors — from `asset_state`. Log-payment modal → `/api/plans/<id>/payments`,
  re-fetch. App-shell rows are now anchors → `/<type>/<id>`. All cells via createElement (K4).
- INCIDENT: the modal's method/funding-source dropdowns offered values not in the service enums
  (`card`/`salary`/`chit payout`) → clean 400 (K1) but invalid UX. Fixed to mirror
  `assets.py METHODS/SOURCES`. **Rule extension:** K5 pre-flight covers ENUMS too — a `<select>`'s option
  values must equal the service's allowed set, not be guessed.

## 2026-06-04 — Plan 3.4 (Loan detail)
- `/loan/<id>` page: principal-outstanding / interest-due / total cards, accrued/paid/months-behind/as-of
  status line, and the monthly-interest schedule — from `loan_state`. One action modal routes by type:
  disbursement → `/loan/disbursements`; interest/principal → `/loan/entries` (method select shows only
  for entries). All cells via createElement (K4). Note: the loan-entries route does NOT enforce a method
  enum (unlike asset payments) — values are free-form there.

## 2026-06-04 — Plan 3.5 (Holding detail + sharing panel)
- `/holding/<id>` page: value/gain/qty cards, avg-cost + quote status line, Buy/Sell/Set-quote modal →
  `/holding/{buys,sells,quote}`. Reusable `static/assets/sharing.js` (`mountSharing(planId, box)`) renders
  the members list and — owner-only — an add-by-email form + per-contributor remove (`/members`
  endpoints). Mounted on holding/asset/loan detail pages. All DOM via createElement (K4).
- INCIDENT (plan-internal): the plan's holding URL was built dynamically (`"buy"?"buys":"sells"`) but the
  plan's own test asserted the literal `/holding/buys` substring → contradiction. Fixed to literal
  branch URLs (behavior identical). Lesson: when a test asserts a literal substring, the source must
  contain that literal, not assemble it at runtime.
- Phase 3 complete: every existing domain (asset/loan/holding) is fully operable in the browser —
  create, view, log, and share — no curl.

## 2026-06-04 — Plan 4.1 (Chit funds)
- New `chit` plan type, participant-cashflow model: `chits` detail (chit_value/n_members/commission_bps/
  start_date) + ledger kinds chit_contribution(out)/chit_dividend(in)/chit_prize(in). `chit_state`
  derives subscription, totals, net_contributed, and net_position (=prize+dividends−contributed); a pure
  `auction_dividend` calculator (commission, dividend pool, per-member, prize — Decimal, ROUND_HALF_UP).
  Money review confirmed no bare int/int float division anywhere.
- API: create dispatch (asset|loan|holding|chit) + `/chit/entries` (owner-only) + `/chit/dividend?bid=`
  (guarded: bid ≤0 or > chit_value → 400, prevents a negative prize). UI: chit-detail page with a live
  dividend calculator + entry log + sharing panel; create-plan Chit tab; app chit chip/count.
- DEFERRED (Phase 5.2): `money.to_minor("abc")` raises `decimal.InvalidOperation` (an ArithmeticError,
  NOT ValueError), so a malformed numeric string → 500 across ALL money endpoints. Fix centrally in
  money.py (catch InvalidOperation → ValueError) so every endpoint returns 400.

## 2026-06-05 — Plan 4.2 (Secured loans / collateral)
- `loans` gains `secured` (bool, server_default false) + `collateral_plan_id` (FK→plans). A loan pledges
  one same-currency, same-owner holding. `set_collateral` validates (holding/owner/currency); `loan_state`
  derives `collateral={plan_id,name,asset_class,currency,value_minor,ltv_pct}` where
  ltv_pct=round(principal_outstanding×100/value) (Decimal, HALF_UP, null if unquoted). Net worth untouched
  (collateral is informational — the holding is already an asset, the loan a liability).
- INCIDENT (plan didn't anticipate): the 2nd FK loans→plans (collateral_plan_id) caused
  `AmbiguousForeignKeysError` on the Plan.loan/Loan.plan relationship → pinned `foreign_keys` on both
  sides. Also batch-mode rejected the unnamed FK constraint → gave it `fk_loans_collateral_plan_id_plans`.
  Both caught by running the real upgrade. **Rule:** a second FK between the same two tables requires
  explicit `foreign_keys=` on existing relationships; name FK constraints for SQLite batch mode.
- API: create accepts inline `collateral_plan_id` (atomic — a bad id rolls back the whole loan create);
  `POST /loan/collateral` link/unlink (owner-only). UI: loan-detail Collateral section with an LTV badge
  (green<60 / amber 60–80 / red>80) + a pledge modal listing same-currency holdings. createElement-only.

## 2026-06-05 — Plan 4.3 (Retirement / 401(k) planner) — PHASE 4 COMPLETE
- New `retirement` plan type: a pure forward projection (no ledger). `retirements` detail stores inputs
  (current_balance, monthly_contribution, employer_match_bps, annual_return_bps, inflation_bps, current/
  retirement age). `retirement_state` derives the corpus: monthly-compound FV of balance + an
  employer-matched contribution annuity, discounted by inflation for a real-terms figure. **All Decimal,
  `Decimal ** int` for the growth factor (exact, no float, no roots, no math.pow).** Money review
  recomputed every scenario to the minor unit (8%/360mo → ₹1,49,03,594.49 nominal, ₹24,74,621.56 real).
- `update_retirement` merges only settable fields, validates the MERGED dict BEFORE setattr → a bad
  update leaves the row unchanged (atomic). API: create dispatch + `/retirement/update`; UI: planner page
  (corpus nominal+real cards) + Update modal pre-filled from state + create Retirement tab.
- **Phase 4 done:** chit funds + secured loans/collateral + retirement planner — three new domains,
  each backend + UI, money-reviewed. Test suite 127→153.

## 2026-06-05 — Plan 5.1 (Account settings)
- `/settings` page + `set_password`/`update_profile` endpoints (session-authed, no old-password — so
  Google-created `password_hash=None` users can add a password and then use email/password login).
  `_user_json` exposes `has_password` → UI shows "Set" vs "Change". Currency/FX reuse existing endpoints.
  Sidebar Settings is now a real link. createElement-only.

## 2026-06-05 — Plan 5.2 (Hardening sweep)
- **Systemic 500→400 fix:** `money.to_minor`/`to_micro`/`pct_to_bps` now catch `decimal.InvalidOperation`
  → `ValueError`, so a non-numeric amount/rate/quantity on ANY money endpoint returns 400 (the API except
  tuples already catch ValueError) instead of 500. One central change, app-wide. No-float discipline
  proven intact (float→TypeError guard runs before the parse; reviewer reconfirmed).
- Holdings `_add_entry` rejects None quantity/amount with `ValidationError` (was TypeError); edge tests
  added (sell-to-zero, multiple sells, quote=0 → value 0 not None). `fmtMicro` null-guarded on both
  holdings pages.
- Deferred (still logged): unused `session` arg on `*_state`/`net_worth`; `loan_state` `as_of`;
  `ledger_entries(plan_id,kind)` index; DB CHECK/unique constraints; google transport-error handling.

## 2026-06-05 — Plan 5.3 (Analysis tools)
- Stateless **hold-vs-sell** decision calculator (`services/analysis.py:hold_vs_sell`): compare keeping an
  appreciating asset + borrowing against it (paying interest) vs selling. Compound appreciation via
  `Decimal ** int`, simple interest on the borrow over the horizon; `net_hold_advantage = appreciation_gain
  − interest_cost`; verdict hold if net>0 else sell. Pure/derived, no float. New `analysis` blueprint
  (`GET /api/analysis/hold-vs-sell`, auth-gated) + `/analysis` page (verdict green/red). Math constants
  pre-computed + reviewer-recomputed (₹10L gold/10%/₹6L@9%/18mo → net +₹80,112.33, hold).

## 2026-06-05 — Plan 5.4 (Live market feeds, optional) — ROADMAP COMPLETE
- Optional live-price seam mirroring Google sign-in's graceful degradation: `KHATA_PRICE_FEED` config flag
  + injectable `app.config["PRICE_PROVIDER"]` (default `live_price_provider` raises — unwired out of the
  box) + `GET /api/feed/config {enabled}` + owner-only `POST /holding/refresh-quote` (503 when off, 502 on
  provider error, else set_quote from the spot). **Unset ⇒ feeds off ⇒ manual quotes only** — zero
  behavior change by default; a self-hoster supplies a provider to enable. Tested via a stub provider.
  Holding-detail shows a "Refresh price (live)" button only when configured.
- **ENTIRE ROADMAP COMPLETE:** Phases 1–5, 12 plans, 178 tests. App fully built — auth (email/Google),
  sharing, assets, loans (+ secured/collateral), holdings, net worth (+ cross-currency), chit funds,
  retirement planner, settings, analysis, optional feeds — all operable in the browser, money-reviewed,
  no float, derived balances, self-hosted.

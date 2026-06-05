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
  proof_ref?, note?, **amount_status** (`agreed`|`pending`|`countered`), **counter_amount_minor**?,
  **created_at** (when it was logged). Editable in place (see §7). `amount_status` drives the two-party
  contribution-amount agreement (§9): an entry whose attributed contributor (`logged_by_user_id`) differs
  from whoever recorded it starts `pending`; the recorded `amount_minor` still counts toward all totals —
  the status only flags attribution accuracy. Migration `b8a2confirm1`.
- **plan_memberships**: id, plan_id, user_id, role (owner|contributor|…), **status**
  (`invited`|`active`|`declined`), created_at. New shares start `invited`; the plan stays hidden
  from the invitee until they accept (→ `active`). Decline → `declined` (hidden, re-invitable —
  re-inviting a declined user resets them to `invited`). Migration `b7a1m3status1`
  (server_default `active` so pre-existing rows keep working).
- **fx_rates**: id, base_currency, quote_currency, rate_micro, as_of?.

## 5. Enums (authoritative)
- currencies `{INR, USD}` · payment methods `{cash, upi, transfer, cheque}` · funding sources
  `{savings, loan, borrowed, sold_asset, chit_payout, other}` · loan direction `{given, taken}` ·
  interest_type `{none, monthly, yearly}` · loan entry kinds `{interest_payment, principal_repayment}`
  (+ `disbursement` via its own endpoint) · asset_class `{gold, silver, equity, mf, cash, other}` ·
  chit kinds `{chit_contribution, chit_dividend, chit_prize}` · membership status `{invited, active, declined}` ·
  entry amount_status `{agreed, pending, countered}`.

## 6. Derived state contracts (what `GET /api/plans/<id>` returns as `state`, by type)
- **asset_state**: total_price_minor, paid_to_date_minor, remaining_minor, overpaid_minor, next_due_seq,
  installments[{seq, planned_amount_minor, applied_minor, status(paid|partial|due), due_date}], funding_breakdown
  [{source, amount_minor, pct}], contributors[{user_id, display_name, paid_minor, pct, **unconfirmed**}], **ledger**
  [{id, kind, direction, amount_minor, created_at, occurred_at, method, funding_source, note, has_proof,
  logged_by_user_id, paid_by_name, **amount_status**, **counter_amount_minor**}]. (loan_state.ledger carries the
  same amount_status/counter fields.)
- **loan_state**: direction, currency, principal_outstanding_minor, interest_accrued_minor,
  interest_paid_minor, interest_due_minor, total_minor, as_of, schedule[{month_index, period_start,
  expected_minor, applied_minor, status}], next_due_month, months_behind, secured, collateral|null
  {plan_id, name, asset_class, currency, value_minor, ltv_pct}, **ledger** [same shape as asset].
- **holding_state**: asset_class, unit, symbol, purity, currency, qty_held_micro, avg_cost_per_unit_minor,
  cost_of_held_minor, current_price_minor, price_as_of, current_value_minor, unrealized_gain_minor,
  realized_gain_minor, proceeds_minor.
- **chit_state**(chit, as_of=today): currency, chit_value_minor, n_members, commission_bps, subscription_minor,
  total_contributed_minor, total_dividends_minor, prize_received_minor, net_contributed_minor,
  net_position_minor, won, months_recorded, **term_months**, **schedule**[{month_index, period_start,
  expected_minor(=subscription), applied_minor, status(paid|due|upcoming)}], **next_due_month**,
  **next_due_date**, **months_behind**, ledger[{id?, kind, direction, amount_minor, occurred_at, note}].
  Schedule = n_members months from start_date; month `m` is `paid` if `m < months_recorded` (one
  contribution = one month), else `due` if its month has arrived else `upcoming`.
- **retirement_state**: currency, current_balance_minor, monthly_contribution_minor, employer_match_bps,
  annual_return_bps, inflation_bps, current_age, retirement_age, months_to_retirement,
  effective_monthly_minor, total_contributions_minor, projected_corpus_minor, projected_corpus_real_minor.

## 7. API surface (all endpoints)
**Auth** (`/api/auth/*`): POST register · login · logout · google · password · profile · GET config
(`{google_client_id}`) · me (`{user:{id,email,display_name,has_password}}`).
**Plans** (`/api/plans*`): GET `""` (list) · GET `/<id>` (`{plan, state}`) · **PATCH `/<id>`** (edit plan / loan terms — owner) · **DELETE `/<id>`** (delete whole plan — owner) · POST `""` (create, dispatches
on `type`) · POST `/<id>/installments` · POST `/<id>/payments` (asset; accepts **occurred_at**) ·
**PATCH/DELETE `/<id>/entries/<entry_id>`** (edit / delete a ledger entry — owner-only; edit takes amount/
occurred_at/method/funding_source/note; both recompute derived state; editing the amount/attribution
re-opens confirmation) · **POST `/<id>/entries/<entry_id>/amount`** (`{action: confirm|counter|accept, amount?}`
— the two-party amount-agreement loop; accessible to either side, turn-/role-checked) · POST `/<id>/loan/disbursements` · POST `/<id>/loan/entries`
· POST `/<id>/loan/collateral` · POST `/<id>/holding/buys|sells|quote|refresh-quote` · POST
`/<id>/chit/entries` · GET `/<id>/chit/dividend?bid=` · POST `/<id>/retirement/update` · GET/POST
`/<id>/members` (POST returns `{member:{…, status}}` — invited members start `invited`) ·
DELETE `/<id>/members/<user_id>`.
**Invitations** (`/api/invitations*`): GET `""` (`{invitations:[{plan_id, plan_name, plan_type,
currency, role, shared_by, shared_by_email, invited_at}]}` — the current user's pending shares) ·
POST `/<plan_id>/accept` (→ membership `active`) · POST `/<plan_id>/decline` (→ `declined`).
Responding to a non-pending invite → 409; not invited → 404.
**Confirmations** (`/api/confirmations`): GET → `{confirmations:[{plan_id, entry_id, plan_name, plan_type,
currency, amount_minor, counter_amount_minor, from_name, your_role(contributor|owner), actions, occurred_at}]}`
— ledger entries waiting on the current user (pending entries attributed to them, or countered entries on
plans they own); filtered to plans they can access. The action endpoint is `POST /api/plans/<id>/entries/<eid>/amount`.
**Net worth / FX** (`/api`): GET networth · GET dashboard (`{net_position_minor, paid_to_date_minor,
i_owe_minor, owed_to_me_minor, plans:[{id,type,name,currency,role}]}`) · POST base-currency · POST fx-rates.
**Analysis**: GET `/api/analysis/hold-vs-sell?asset_value&appreciation&borrow&interest&horizon`.
**Feed** (optional): GET `/api/feed/config` (`{enabled}`).
**Backup** (`/api`): GET `/backup` → whole-instance JSON snapshot of every table, as a file download
(`khata-backup-<date>.json`, `no-store`) · POST `/restore` (multipart `file` or raw JSON body) → MERGE the
backup in (users matched by email, plans+children inserted fresh with remapped FKs), auto-saving a
pre-restore snapshot first; returns `{ok, stats, pre_restore_saved}`. Both authenticated.

**Authorization:** mutations are **owner-only** (`_owned_plan`); reads are owner-or-**active**-member
(`_accessible_plan` → `sharing.accessible`, which now requires status `active`, so an invited member
can't view the plan until they accept). `paid_by` tagging uses the looser `sharing.on_plan` (owner or
any non-declined membership) so an invited-but-not-yet-accepted contributor can still be attributed on
entries. Unauthenticated → 401; not found → 404; not yours → 403. Pattern: validate → mutate →
`commit` on success / `rollback` on error.

## 8. Pages / routes (static, client-rendered; auth guard `/api/auth/me` 401→`/`)
`/` landing (marketing + embedded sign-in modal) · `/features` · `/app` dashboard (sidebar, stat cards,
plan panels, Lent panel, chit badges) · `/create` (4-step wizard modal, all 5 types) · `/holdings`
(net worth + table + hold-vs-sell) · `/asset/<id>` (KPIs, schedule, **ledger w/ edit**, funding,
contributors, log-payment slide-over w/ **date**) · `/loan/<id>` (at-a-glance, release schedule, ledger,
collateral when secured) · `/chit/<id>` (stats, rounds table, ledger) · `/holding/<id>` · `/retirement/<id>`
(NPS projector) · `/settings` · `/analysis`.

## 9. Enhancements beyond the intent brief (record new ones here)
- **2026-06-05 — Whole-instance backup & restore (data portability).** "Your data is yours" — two paths,
  both shipping. (1) **In-app JSON**: `GET /api/backup` downloads a single versioned snapshot of every table
  (`services/backup.export_all` — generic over the mapper, robust to schema changes); `POST /api/restore`
  **merges** an uploaded backup (`import_merge`): users matched by email (existing reused, missing created),
  all plans + 1:1 sub-rows + installments + ledger_entries + memberships + fx inserted fresh with FKs
  remapped to the target instance's ids (loan collateral refs remapped too; fx deduped by base/quote/as_of).
  Merge = adds-on-top (re-importing duplicates plans — warned in the UI); a pre-restore snapshot is auto-saved
  server-side to `backups/` first. Settings → **Data** panel: "Download backup" + "Restore from file"
  (confirm + stats). (2) **CLI raw-SQLite** (`scripts/backup.sh` / `restore.sh`): exact byte snapshot via
  SQLite online `.backup`, restore = file REPLACE (integrity-checked, typed confirm, saves a pre-restore copy).
  Decisions: whole-instance scope · both mechanisms · JSON=merge / CLI=replace (a file swap can't merge).
- **2026-06-05 — Chit monthly contribution schedule + next-due.** A chit runs `n_members` months (one
  auction/month) from `start_date` — now surfaced as a month-by-month schedule (no schema change; derived in
  `chit_state`). Each recorded contribution covers one month in order; remaining months are `due` (arrived) or
  `upcoming` (future). `chit_state` gains `schedule`, `term_months`, `next_due_month`, `next_due_date`,
  `months_behind` (+ an optional `as_of` param for testing). Frontend: chit-detail **Contribution schedule**
  panel — a 12-cell month grid (green=paid, red=due, faint=upcoming) with a "Next due · <month>" banner that
  turns red "⚠ N months overdue" when behind. (How the user uses chit: solo member, or operating a
  spouse/family member's own account — single-owner either way, so chit deliberately has **no** paid-by /
  amount-confirmation flow. Win/return projection deferred to a follow-up.)
- **2026-06-05 — Two-party contribution-amount agreement (per-entry, counter-propose loop).** Phase 2 of
  consent. When the owner records "₹2,00,000 · paid by Priya", the entry starts `pending` — Priya must
  confirm or correct it; neither side dictates. Decisions taken: **per-ledger-entry** granularity ·
  **counter-propose loop** (either side proposes, the other accepts or counters, until both match) ·
  the interim recorded amount **still counts toward all totals/shares, flagged 'unconfirmed'** (so the
  dashboard is never silently wrong). State machine on `ledger_entries.amount_status`
  {`agreed`|`pending`|`countered`} + `counter_amount_minor`: self-/owner-logged → `agreed`; third-party-
  attributed → `pending`; contributor counter → `countered` (recorded amount untouched until accepted);
  owner accept → amount becomes the counter, `agreed`; owner re-counter → new amount, back to `pending`.
  Editing an entry's amount/attribution re-opens confirmation. Service: `assets.respond_amount`,
  `assets.list_amount_confirmations`, `_amount_status_for`; logging fns take `acting_user_id`. API:
  `POST /api/plans/<id>/entries/<eid>/amount` (turn/role-checked) + `GET /api/confirmations`. Frontend:
  dashboard **amber confirmation banner** (Confirm/Propose for the contributor, Accept/Counter for the
  owner, inline amount input); asset/loan detail ledger rows show a **⚠ unconfirmed / ⇄ counter-proposed**
  chip; asset contributor breakdown marks unconfirmed people with ⚠. (Chit entries have no paid-by, so
  always `agreed`.) Completes the user's "both have the option to make the value accurate" ask.
- **2026-06-05 — Two-party sharing consent (membership invitations).** Adding a user who has an account no
  longer silently grants access. New shares create a membership with status `invited`; the plan stays
  hidden from the invitee (`accessible` = owner-or-`active`) until they respond. The invitee sees a
  **pending-shares banner** on the dashboard ("X shared a <type> with you · 'Plan' · awaiting your approval")
  with **Accept** / **Decline**. Accept → `active` (plan now in their `/api/plans` + dashboard, page reloads
  to surface it); Decline → `declined` (hidden; re-invitable — re-adding resets to `invited`). Endpoints:
  `GET /api/invitations`, `POST /api/invitations/<plan_id>/accept|decline`. The owner's "Shared with" list
  (sharing.js) shows a **pending** chip for invited members; the paid-by dropdowns mark them "(pending)".
  Data: `plan_memberships.status` + migration `b7a1m3status1`. (Phase 1 of the consent flow; Phase 2 —
  the invitee accepting/​correcting the **money amount** attributed to them — is the entry above.)
- **2026-06-05 — Editable ledger.** `PATCH /api/plans/<id>/entries/<entry_id>` (owner-only) edits an
  existing entry's amount/occurred_at/method/funding_source/note; `kind`/`direction` immutable; derived
  balances recompute. Frontend: ✎ edit on each asset-detail ledger row reopens the slide-over pre-filled.
- **2026-06-05 — Payment date.** Log-payment slide-over has a "Date (when it happened)" field → `occurred_at`
  (distinct from auto `created_at` = when logged). Ledger shows "· logged X" when the two differ.
- **2026-06-05 — Tag who paid (contributor per entry).** Log-payment / add-disbursement / edit-entry forms gain a **Paid by · contributor** dropdown (plan members; shown only when the plan is shared with >1 member). Sends `paid_by` = a member's user_id; the API validates membership (400 otherwise) and sets the entry's `logged_by_user_id`. Asset contributor shares + the ledger 'paid by X' line reflect it — so joint buys and co-funded loans (e.g. ₹2L + ₹8L of a ₹10L loan) are auditable per person. Ledger rows now expose `logged_by_user_id` + `paid_by_name`. On asset-detail and loan-detail.
- **2026-06-05 — Edit / delete a whole plan.** `PATCH /api/plans/<id>` edits a plan (loan terms: name/direction/counterparty/interest_type/rate/start_date/tenure; other types: name) and `DELETE /api/plans/<id>` removes the whole plan + all its entries (owner-only, cascades). Frontend: loan-detail header has polished **✎ Edit** + **Delete** ghost buttons. The Edit slide-over includes a **Principal** field (maps to disbursements: creates the opening one if none, patches the single existing one, or notes tranches → edit on ledger) — so a ₹0 loan can be corrected in place. Loan summary now exposes start_date + tenure_months for pre-fill. (Before this, plan terms couldn't be corrected and plans couldn't be deleted.)
- **2026-06-05 — Loan create asks for Principal.** The create-plan loan step now has a required **Principal (amount borrowed/lent)** field. On submit it creates the loan plan then logs the opening amount via `POST /loan/disbursements` (dated the start date) — so the loan has its principal immediately and interest/outstanding compute. (Khata models principal as dated disbursements → later top-ups/tranches still work.) Was a real flaw: loans were created with ₹0 and nothing could be calculated.
- **2026-06-05 — Edit/Delete on loan & chit ledgers** (same as asset): ✎ edit per row → slide-over → PATCH/DELETE /entries/<id>. chit_state.ledger now carries id+created_at.
- **2026-06-05 — Sidebar type = focused list.** Picking Assets/Chit/Loans/401(k) now shows a clean **list of only that type** (hides the stat cards, featured panel, and Liabilities/Lent) — each row links to its detail page (where edit/delete live). Dashboard (no filter) still shows the full layout. Fixes the confusion of the filtered dashboard looking like an 'asset page' with a no-edit ledger.
- **2026-06-05 — Define/edit a schedule on an existing asset.** Asset-detail schedule panel has **"+ add schedule"** (when ad-hoc) / **"✎ edit schedule"** (when scheduled) → a slide-over with an installment builder (amount + due date, add/remove rows) → `POST /api/plans/<id>/installments` (replaces the schedule; logged payments re-apply since balances are derived). `asset_state.installments` now also carries `due_date` (for pre-fill). So an ad-hoc asset can become scheduled later.
- **2026-06-05 — Delete ledger entry.** `DELETE /api/plans/<id>/entries/<entry_id>` (owner-only; recomputes derived state). Frontend: a **Delete** action in the asset-detail edit slide-over (shown only when editing, confirm before delete).
- **2026-06-05 — Ad-hoc (unscheduled) assets.** Assets with no installments now read "X% paid · ad-hoc payments" and the schedule panel shows "No fixed schedule — payments are logged as funds arrive" (instead of "0 of 0 installments"). Valid pattern: pay as funds arrive.
- **2026-06-05 — Sidebar type filter.** Dashboard sidebar Assets/Chit/Loans/401(k) now link `/app?type=<t>`
  → the "Your plans" list filters to that type, the nav item highlights, the panel relabels, and it scrolls
  into view (were all dead `href=/app`). Holdings still → `/holdings`.
- **2026-06-05 — Log out.** **Every app page's** sidebar has a **Log out** item → `POST /api/auth/logout` then
  redirect `/` (the rich dashboard had shipped without one). Endpoint already existed.
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
- **Backup/restore**: in-app (Settings → Data) downloads/uploads a whole-instance JSON; or operator CLI
  `scripts/backup.sh [DB] [DEST]` (online SQLite `.backup`, safe while live) + `scripts/restore.sh BACKUP [DB]`
  (file replace; stop the app first). Auto-saved snapshots land in `<db_dir>/backups/` (gitignored). Back up
  `khata_app.db` regularly — it's the only source of truth.
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
- 2026-06-05 — Whole-instance backup & restore: in-app JSON download/upload (merge by email + FK remap, pre-restore auto-save) + CLI raw-SQLite backup.sh/restore.sh (replace). `GET /api/backup`, `POST /api/restore`, Settings → Data panel.
- 2026-06-05 — Chit monthly contribution schedule + next-due reminder (chit_state.schedule/next_due_date/months_behind; chit-detail month-grid panel). Derived, no schema change.
- 2026-06-05 — Per-entry contribution-amount agreement: a tagged contributor confirms or counter-proposes the amount attributed to them; owner accepts or re-counters until both agree. `ledger_entries.amount_status`/`counter_amount_minor` + `/api/confirmations` + `POST .../entries/<id>/amount`. Interim amount counts toward totals, flagged unconfirmed.
- 2026-06-05 — Two-party sharing consent: invited members get a pending-approval banner (Accept/Decline) before the shared plan becomes visible. `plan_memberships.status` + `/api/invitations`.
- 2026-06-05 — Can tag who paid/contributed each entry (paid_by → contributor shares + audit).
- 2026-06-05 — Fixed dashboard 'flash' when filtering: widgets hide AND the sidebar highlight is set synchronously (pre-paint) on ?type, so refresh no longer flashes Dashboard→type.
- 2026-06-05 — Sidebar type links now carry ?type on ALL pages (was one-click only from the dashboard; two clicks from detail pages).
- 2026-06-05 — Loan edit form includes Principal (fixes ₹0 loans); Edit/Delete restyled as proper buttons.
- 2026-06-05 — Can edit a loan's terms + delete a whole plan (PATCH/DELETE /api/plans/<id>).
- 2026-06-05 — Loan create form now captures Principal (logs opening disbursement).
- 2026-06-05 — Edit/Delete on loan & chit ledgers; sidebar type shows a focused list (not the full dashboard).
- 2026-06-05 — Can define/edit installment schedule on an existing asset (POST /installments from the detail page).
- 2026-06-05 — Ledger entries can be deleted (DELETE /entries); ad-hoc (no-installment) asset copy cleaned up.
- 2026-06-05 — Dashboard sidebar type items (Assets/Chit/Loans/401k) filter the plan list via ?type.
- 2026-06-05 — Landing: nav + hero 'Sign in' open the sign-in/create modal in one click (was scroll-then-click).
- 2026-06-05 — Added Log out to every app page's sidebar (dashboard + 9 detail/tool pages).
- 2026-06-05 — Created this as-built spec. Recorded: editable ledger (PATCH /entries), payment occurred_at
  vs created_at, ledger exposure in asset/loan state, single-port deploy (:5057). Full app on
  `feat/landing-page` (PR #14); roadmap Phases 1–6 done; deviations/deferrals in §10.

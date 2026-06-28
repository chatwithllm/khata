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
  `KHATA_ENV`, `KHATA_GOOGLE_CLIENT_ID` (optional), `KHATA_PRICE_FEED` (optional),
  `KHATA_SECURE_COOKIES` (optional — behind an HTTPS reverse proxy).
- Frontend rule **K4 (XSS):** all dynamic DOM via `createElement` + `textContent`; **never** `innerHTML`
  on user/API data. Pages: `ledger.css` (landing/marketing, `.landing`-scoped animations) + `app.css`
  (app shell + detail panels); `sharing.js` (`mountSharing`). HTML served `Cache-Control: no-store`.

## 4. Data model (14 tables)
- **users**: id, email, display_name, password_hash?, google_sub?, base_currency, **avatar?** (cropped
  square profile photo as a `data:image/...` URL, set via the crop tool; stored server-side so every member
  sees each contributor's photo and it travels with backups), **is_admin**, **disabled**, created_at.
  Migrations `c9a3avatar01` (avatar), `de8admin01` (is_admin/disabled — bootstraps the first user as admin).
  **is_admin** = manage users + backup/restore (see §11); the first user to register is auto-admin (in
  `register_user`/`login_with_google` and via the migration). **disabled** = a reversible login block:
  `authenticate_user`/Google login return 403 `account_disabled` and `current_user` stops resolving a
  disabled user's live session, without deleting any data.
- **plans** (spine): id, owner_user_id, **type** (asset|loan|holding|chit|retirement), name, currency,
  status, created_at. 1:1 → asset/loan/holding/chit/retirement; 1:N → installments, ledger_entries,
  memberships.
- **asset_purchases**: plan_id, total_price_minor, **seller_name?**, **seller_contact_id?** (FK→contacts,
  ON DELETE SET NULL), **buyer_name?**, **buyer_contact_id?** (FK→contacts, ON DELETE SET NULL),
  **extra_fields?** (Text/JSON `[{label, value}]` — custom info rows), **links?** (Text/JSON
  `[{label, url, video}]` — external links; http(s)-only URLs, `video: true` renders as ▶).
  Migration `as1assetmeta01`.
- **installments**: id, plan_id, seq, planned_amount_minor, due_date?, note?.
- **loans**: plan_id, direction (given|taken), **kind** (personal|gold|home|vehicle|education|business|other —
  the loan category; default personal; migration `ca4loankind01`), counterparty?, interest_type
  (none|monthly|yearly), rate_bps, basis, repayment, start_date, tenure_months?, secured (bool),
  collateral_plan_id? (FK→plans). **Inline collateral** (e.g. gold loan): collateral_qty_micro?
  (weight ×1e6), collateral_unit? (gram|ounce), collateral_rate_minor? (price at loan time),
  collateral_rate_basis? (per_gram|per_10gram|per_ounce), collateral_value_minor? (market value → drives LTV).
  Migration `cb5goldcoll01`.
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
  the status only flags attribution accuracy. Migration `b8a2confirm1`. **funding_plan_id?** (FK→plans): provenance link — an asset contribution paid out of a loan points to that loan (migration `cc6fundlink01`); each plan still counts only its own entries, the link just records the money's chain.
- **plan_memberships**: id, plan_id, user_id, role (owner|contributor|…), **status**
  (`invited`|`active`|`declined`), created_at. New shares start `invited`; the plan stays hidden
  from the invitee until they accept (→ `active`). Decline → `declined` (hidden, re-invitable —
  re-inviting a declined user resets them to `invited`). Migration `b7a1m3status1`
  (server_default `active` so pre-existing rows keep working).
- **plan_shares** (public read-only share links): id, **plan_id** (FK→plans, ON DELETE CASCADE),
  **token** (unguessable `secrets.token_urlsafe(32)`, unique), **scope** (`summary`|`full`), **expires_at**,
  **revoked_at?**, created_by_user_id, created_at. A link is valid iff not revoked and not past expiry.
  Migration `sh1share01`.
- **attachments** (supporting proof on a ledger entry, contact, or asset plan): id, **ledger_entry_id?** (FK→ledger_entries,
  ON DELETE CASCADE, nullable), **contact_id?** (FK→contacts, ON DELETE CASCADE, nullable),
  **asset_plan_id?** (FK→plans, ON DELETE CASCADE, nullable — exactly one of three parents; indexed),
  uploaded_by_user_id, filename, **mime** (decided by MAGIC BYTES, never the
  extension), size, **sha256**, **data** (`LargeBinary` blob — bytes live in the DB so the one-file
  JSON backup keeps round-tripping; the backup serializer base64-encodes the blob on export/import),
  created_at. Allowlist: images (jpeg/png/gif/webp/heic), PDF, Office (docx/xlsx/pptx + legacy OLE);
  a bare zip is rejected. 25 MB/file cap; photos are downscaled client-side (drops EXIF/GPS). Lights
  the `▣ proof` tag (`has_proof = proof_ref OR attachments`) and `attachment_count` on the entry.
  Access: owner OR the entry's contributor may upload/delete; any shared member may view. Served from
  `/api/attachments/<id>` with the stored mime (images/PDF inline, else download), membership-gated,
  `X-Content-Type-Options: nosniff`. Migration `ct1contact01` (added contact_id).
- **contacts** (people you lend to / borrow from — owner-private): id, owner_user_id, name,
  phone?, email?, address?, notes?, photo? (data:URL), created_at, updated_at. Loans link via
  `loans.contact_id` (nullable FK, **ON DELETE SET NULL** — deleting a contact unlinks its loans,
  never deletes them). Migration `ct1contact01`.
- **fx_rates**: id, base_currency, quote_currency, rate_micro, as_of?.
- **backup_config** (singleton, id=1): enabled, frequency (`daily`|`weekly`), hour (0–23 server-local),
  retention (keep last N), last_run_at, last_status. Drives the in-app automatic-backup scheduler
  (migration `df9backup01`; NOT included in backup exports — it's instance-local). `last_run_at` doubles
  as the cross-worker claim token (`backup_store.claim_due`) so two gunicorn workers never double-back-up.

## 5. Enums (authoritative)
- currencies `{INR, USD}` · payment methods `{cash, upi, transfer, cheque}` · funding sources
  `{savings, loan, borrowed, sold_asset, chit_payout, other}` · loan direction `{given, taken}` ·
  interest_type `{none, monthly, yearly}` · loan kind `{personal, gold, home, vehicle, education, business, other}` · loan entry kinds `{interest_payment, principal_repayment, fee}`
  (+ `disbursement` via its own endpoint) · asset_class `{gold, silver, equity, mf, cash, other}` ·
  chit kinds `{chit_contribution, chit_dividend, chit_prize}` · membership status `{invited, active, declined}` ·
  entry amount_status `{agreed, pending, countered}`.

## 6. Derived state contracts (what `GET /api/plans/<id>` returns as `state`, by type)
- **asset_state**: total_price_minor, paid_to_date_minor, remaining_minor, overpaid_minor, next_due_seq,
  installments[{seq, planned_amount_minor, applied_minor, status(paid|partial|due), due_date}], funding_breakdown
  [{source, amount_minor, pct}], contributors[{user_id, display_name, **avatar**, paid_minor, pct, **unconfirmed**}],
  **seller** `{name, contact_id, contact_name}|null`, **buyer** `{name, contact_id, contact_name}|null`,
  **extra_fields** `[{label, value}]`, **links** `[{label, url, video}]`, **attachments** (list; scrubbed
  from public share links),
  **ledger** [{id, kind, direction, amount_minor, created_at, occurred_at, method, funding_source, note, has_proof,
  logged_by_user_id, paid_by_name, **paid_by_avatar**, **amount_status**, **counter_amount_minor**}].
  (loan_state.ledger carries the same amount_status/counter fields.)
- **loan_state**: direction, currency, principal_outstanding_minor, interest_accrued_minor,
  interest_paid_minor, interest_due_minor, total_minor, as_of, schedule[{month_index, period_start,
  expected_minor, applied_minor, status, cum_due_minor, principal_minor, total_owed_minor}], next_due_month, months_behind, secured, collateral|null
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
**Auth** (`/api/auth/*`): POST register · login · logout · google · password · profile · **avatar**
(`{avatar: <data-url|null>}` — validates `data:image/` prefix + ~200 KB cap; clears on null) · GET config
(`{google_client_id}`) · me (`{user:{id,email,display_name,has_password,avatar}}`).
**Dual auth:** every protected route resolves the user via `current_user()`, which accepts **either** the web session cookie **or** an `Authorization: Bearer <token>` header (for the mobile client). register/login/google responses include `token` (stateless, `itsdangerous`-signed user id, 30-day expiry; `src/khata/tokens.py`). `/api/*` carries permissive CORS (wildcard origin, `Authorization`+`Content-Type` headers, OPTIONS preflight → 204; no Allow-Credentials).
**Plans** (`/api/plans*`): GET `""` (list) · GET `/<id>` (`{plan, state}`) · **PATCH `/<id>`** (edit plan / loan terms — owner) · **DELETE `/<id>`** (delete whole plan — owner) · POST `""` (create, dispatches
on `type`) · POST `/<id>/installments` · POST `/<id>/payments` (asset; accepts **occurred_at**) ·
**PATCH/DELETE `/<id>/entries/<entry_id>`** (edit / delete a ledger entry — owner-only; edit takes amount/
occurred_at/method/funding_source/note; both recompute derived state; editing the amount/attribution
re-opens confirmation) · **POST `/<id>/entries/<entry_id>/amount`** (`{action: confirm|counter|accept, amount?}`
— the two-party amount-agreement loop; accessible to either side, turn-/role-checked) · POST `/<id>/loan/disbursements` · POST `/<id>/loan/entries`
· POST `/<id>/loan/collateral` · **GET `/<id>/loan/amortization?extra=&lump=&lump_month=&target_months=`**
(repayment projection: EMI + baseline + optional what-if scenario — months/interest saved) · **POST
`/<id>/loan/compare`** (`{amount?, offers:[{label, rate, interest_type?, tenure_months?, fee_pct?, fee_amount?}]}`
→ shop-around comparison vs the current loan: EMI, total interest, fee, total cost, effective APR per offer,
cheapest flagged) · **GET `/loans/grouped`** → grouped-by-contact rollup (per-currency→base) + sankey nodes/links
· **PATCH `/<id>/asset/meta`** (update asset seller/buyer/extra_fields/links — owner-only; 400 on bad
input or non-http(s) URL; blank seller/buyer names stripped; extra_fields/links rows capped and cleaned)
· **GET `/<id>/asset/attachments`** (list asset document attachments — plan-member accessible) · **POST
`/<id>/asset/attachments`** (upload asset document — owner-only; 413 if over size cap)
· POST `/<id>/holding/buys|sells|quote|refresh-quote` · POST
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
(`khata-backup-<date>.json`, `no-store`) · POST `/restore` (multipart `file` or raw JSON body) → REPLACE: every
backed-up table is wiped then loaded verbatim (original ids preserved); backups with no users rejected (400);
`backup_config` and `fx_refresh_state` are not touched; operator session re-pointed by email after restore —
if their account isn't in the backup, session is cleared and `logged_out: true` is returned; a pre-restore
snapshot is auto-saved first; restoring the same file twice is idempotent; returns
`{ok, stats: {<table>: count, …}, pre_restore_saved, logged_out}`. Both authenticated.

**Attachments:** `GET/DELETE /api/attachments/<id>` extended with an `asset_plan_id` branch: download is
plan-member accessible (`sharing.accessible`); delete is owner-or-uploader. `GET /api/attachments/<id>`
serves with stored mime (images/PDF inline, else download), `X-Content-Type-Options: nosniff`.
**Authorization:** plan-level mutations are **owner-only** (`_owned_plan`); **ledger-entry** edit/delete are **owner OR the entry's own contributor** (`_editable_entry`); reads are owner-or-**active**-member
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
- **2026-06-19 — Asset details: parties, custom fields, links, and document attachments.**
  Assets gain seller & buyer (free text + optional Contact link via `seller_contact_id`/`buyer_contact_id`,
  FK contacts SET NULL), custom info rows (`extra_fields` JSON `[{label,value}]`) and external links
  (`links` JSON `[{label,url,video}]` — http(s)-only; `video:true` renders as ▶ link, never an upload —
  so the one-file backup property is preserved). Document attachments supported via a third attachment
  parent: `asset_plan_id` on the `attachments` table (FK→plans CASCADE, indexed). Owner edits via
  `PATCH /api/plans/<id>/asset/meta` (400 on bad input or non-http(s) URL); asset docs: upload
  owner-only (`POST /asset/attachments`), listing + download plan-member accessible (`GET
  /asset/attachments`, `GET /api/attachments/<id>`). seller/buyer/extra_fields/links/url scrubbed from
  public share links (`_SCRUB_KEYS` in `sharing_links.py`; attachments already scrubbed). UI:
  `asset-detail.html` — Parties display (contact links), Edit-details slide-over, Details card, Links
  card, Documents card (upload/list/download/delete). Migration `as1assetmeta01`
  (down_revision `ct1contact01`).
- **2026-06-19 — Loans grouped by contact + Sankey.** By-direction ↔ By-contact toggle on the Loans page: By-contact
  groups loans per person (contact name, else counterparty; same names merge), given/taken within each, with a
  one-glance summary (principal · expected interest/mo · next-month due) in base currency. Hand-rolled SVG Sankey
  (Direction → Contact → Loan, weighted by outstanding) sits above the list, with a stacked-bar fallback on small
  screens / reduced-motion / large books. Powered by a new read-only `GET /api/plans/loans/grouped` (owner-only)
  that computes the aggregation + sankey nodes/links server-side (reuses loan_state + fx). No migration.
- **2026-06-19 — Contacts + per-contact loan grouping.** A contact record (name/phone/email/address/notes/photo
  + document attachments via the attachments table) that loans link to (`loans.contact_id`, manual assign, SET NULL
  on delete). Per-contact rollup of principal + interest — per-currency subtotals plus a base-currency grand total
  (FX-converted, flagged partial when a rate is missing). New `contacts` table (migration `ct1contact01`), contacts
  service + API (`/api/contacts` CRUD, `/api/plans/<id>/loan/contact` assign, `/api/contacts/<id>/attachments` docs),
  Contacts sidebar section + list + detail pages. Owner-only; contact PII excluded from shared/public views.
- **2026-06-19 — Public read-only share links.** Any plan (asset/loan/holding/chit/retirement) can be
  shared via a tokenized public URL (`/s/<token>`, no login) with expiry (7/30/90 days) + revoke and a
  per-share `summary`|`full` (PII-redacted) scope; plus token-less Print and navigator.share "send".
  New `plan_shares` table (migration `sh1share01`), `sharing_links` service (recursive PII scrub),
  public blueprint `GET /api/public/<token>` (404/410), owner-only `POST/GET/DELETE /api/plans/<id>/shares`,
  standalone print-friendly `/s/<token>` page (CSP, robots:noindex).
- **2026-06-19 — Backfill historical loan payments.** Loan detail gains a per-row + bulk "mark through Month N" UI to record backdated interest payments/receipts against past schedule months. Backend: new `services.loans.backfill_loan_interest` service + owner-only `POST /api/plans/<id>/loan/backfill` endpoint. Both reuse the existing greedy interest pool (no schema change, no migration), creating timestamped `interest_payment` entries in the past. Idempotent — paid months are skipped. Wording follows loan direction (paid/received). Solves the real-world retroactive payment problem: "I paid interest for three months but didn't log it until now."
- **2026-06-11 — Per-entry FX rate snapshots (live currency conversion).** Every ledger entry now
  freezes the exchange rate at log time so its counter-currency value is exact forever (spec
  `docs/specs/2026-06-11-fx-snapshot-design.md`). `ledger_entries.fx_rate_micro` (counter-per-entry
  ×1e6) + `fx_counter_currency` + single-row `fx_refresh_state` claim table, migration `fxsnapshot01`.
  New stdlib-only `services/fx_live.py` frankfurter.app client (ECB daily fixes; swallows every
  failure → None/{}; NOTE its direction is quote-per-base — the OPPOSITE of `fx.get_rate`'s
  base-per-quote). Snapshot fallback chain in `fx.snapshot_entry_rate`: explicit client rate →
  live fetch for the entry's occurred_at date → stored Settings rate → NULL (never blocks a save).
  Hooked into all six entry-creating services (asset payment, loan disbursement/entry, holding
  buy/sell, chit entry). API: create + PATCH entry accept `fx_rate_micro` (positive int else 422);
  PATCH is metadata-only — editing the rate never re-opens amount confirmation. The counter value is
  always DERIVED via `fx.convert` (`counter_value_minor` in state ledgers), never stored. Dashboard
  paid-to-date converts per-entry: same-currency passthrough → entry snapshot → current rate (NULL
  entries keep old behavior). Hourly scheduler tick claims one daily refresh atomically across
  gunicorn workers (`fx.claim_daily_refresh`, claim released on fetch failure for same-day retry)
  and stores USD/INR via `fx.set_rate` in the Settings-compatible direction. Admin
  `POST /api/admin/fx-backfill` stamps historical NULL-rate entries from ONE frankfurter range call
  (weekend → walk back ≤7 days; INR entries get the exact Decimal inverse) — **prod DB write: run
  once, manually, only on explicit user authorization**. UI: `assets/fx.js` renders a quiet mono
  "$568.20 @ ₹88.00/$" line under ledger amounts on asset/loan/chit detail; the three edit forms
  gain an FX-rate field prefilled in natural direction (1 USD = ₹) that PATCHes only when edited
  non-empty; Settings FX hint documents the daily auto-refresh.
- **2026-06-06 — Tablet & mobile responsive shell.** The fixed 240px sidebar became an **off-canvas drawer** at ≤880px: a hamburger (injected into every topbar by the shared `static/assets/nav.js`) toggles `.nav-open` on `.app`, sliding the sidebar in over a scrim (Esc / scrim / nav-tap closes). Topbar shrinks + the greeting truncates so the actions stay; content/panel padding reduces; `.kpis` and dashboard `.stats` stack to one column on phones; the loans list drops its secondary interest/mo column (`.pr-icol`) on phones. `nav.js` added to all app pages (guards on `.app`/`.top`/`.side`); responsive `@media` overrides kept at the END of app.css so they beat the base shell rules. (Landing page already had its own responsive.)
- **2026-06-06 — Fund a contribution from a loan (cross-plan money chain).** Real flow: you borrow ₹10L → it becomes your asset contribution → you repay the loan. The asset payment now links to its source loan via `ledger_entries.funding_plan_id` (link-only — the loan disbursement and the asset payment stay separate real events; no double-count). Asset log-payment shows a **“from which loan”** picker when funding source is loan/borrowed; the asset ledger row shows a **“↗ <loan>”** link; loan-detail gains a **“Deployed into”** panel listing where the borrowed money went + total put to work. Payoff is the existing principal_repayment flow. `loan_state` gains `deployed[]`/`deployed_total_minor`; `asset_state.ledger` rows gain `funding_plan_id/name/type`. (Plan.ledger_entries relationship pinned to plan_id FK to disambiguate the new second FK.)
- **2026-06-06 — Differentiable plan rows in the list (esp. loans).** The dashboard "Your plans" / filtered
  list showed only "<Name> · INR · owner" — two same-named gold loans were indistinguishable before opening.
  Now each row has a `planMeta(p)` line built from the summary (loan → "Gold · from SBI · 7.5%/yr"; holding →
  asset_class · symbol; chit → N members; retirement → age range) + a small category **chip** on non-personal
  loans, and **loan rows fetch state** to show the **outstanding amount** on the right with a caption
  ("outstanding", or **"LTV 86%"** colour-flagged for gold loans). So "Gold · from SBI · ₹2,00,000 · LTV 86%"
  vs "Gold · from Muthoot · ₹40,000 · LTV 84%" read apart at a glance. Client-only (app.html); no API change.
- **2026-06-06 — Gold-loan collateral details + loan-to-value.** When the loan kind is gold, create-plan and
  edit-terms reveal a **Gold pledged** block: weight (grams / troy oz), the rate at loan time (per gram /
  per 10 g / per troy oz), and market value (auto-filled = weight × rate, editable). Stored inline on the loan
  (`collateral_qty_micro/unit/rate_minor/rate_basis/value_minor`, migration `cb5goldcoll01`; set/cleared via
  `_apply_collateral`, cleared automatically when the kind moves off gold). loan-detail "At a glance" shows
  Gold pledged / Rate at loan time / Collateral value / **Loan-to-value** (= principal_outstanding ÷ value,
  in `loan_state.gold_collateral`; colour-flagged — green ≤60%, amber 75–100%, and **>100% is treated as an
  error**: glance shows "⚠ NN%" + an explainer ("loan exceeds the recorded gold value — check weight/value/
  principal, likely a missing digit"), the dashboard list caption shows "⚠ LTV NN%" red, and the edit-terms
  slide-over computes a **live LTV** under the value field as you type. `_gold_collateral` parses the
  `gold_*` body fields. So a gold loan now records exactly what's pledged and surfaces the lender's key ratio.
- **2026-06-06 — Loan category (kind) — meaningful collateral, not just "unsecured".** A loan now carries a
  `kind` (personal | gold | home | vehicle | education | business | other), picked in the create-plan loan
  step and editable in the edit-terms slide-over. loan-detail "At a glance" shows a **Type** row, and the
  **Security** row now derives from the kind when no holding collateral is linked: gold→"secured · gold",
  home→"secured · property", vehicle→"secured · vehicle"; personal/education/business → "unsecured" (a
  linked holding still overrides with its name). Was: every loan showed a bare "unsecured" with no sense of
  what it was. Model `loans.kind` + migration `ca4loankind01`; `create_loan_plan`/`update_loan_terms` +
  `LOAN_KINDS`; `_summary` exposes `kind`; `loan_kind` in create + PATCH bodies.
- **2026-06-05 — Loan shop-around comparison (true cost vs other lenders).** A "Compare lenders" panel on
  loan-detail that pits the current loan against user-entered offers (e.g. BofA, Prosper) on a like-for-like
  principal. Financial-advisor framing: ranks by **total cost** (interest + upfront fee) and **effective APR**
  — the APR is fee-inclusive (`_apr_bps` = monthly IRR equating principal−fee to the EMI stream, annualised),
  so a low headline rate with a big origination fee is exposed (e.g. 9% nominal + 5% fee → 15.1% APR).
  `loans.compare_offers` + `POST /api/plans/<id>/loan/compare`. UI: a metrics×lenders table (rate, term,
  upfront fee, monthly payment, total interest, **total cost**, **effective APR**) with the cheapest column
  green-tinted + "✓ best" and a "vs your loan · save ₹X / +₹Y" row; an add-offer form (lender, rate %, term,
  fee %). Offers are client-side/exploratory (not persisted). Tested (`test_amortization.py`).
- **2026-06-05 — Loan repayment projection (amortization + payoff what-ifs).** A "Repayment plan" panel on
  loan-detail that projects a fixed-EMI repayment of the **current outstanding** over the loan's tenure, then
  lets you model paying it off faster. Pure integer-minor math, server-side + tested (`loans.amortize` +
  `_simulate`/`_emi`/`_monthly_rate`): EMI = P·mr/(1−(1+mr)⁻ⁿ); month-by-month simulation gives total
  interest, payoff date, and (for a what-if) months-saved + interest-saved vs baseline. Three what-ifs (all
  chosen): **extra ₹/month**, **one-time lump sum**, **target payoff month** (→ required payment).
  `GET /api/plans/<id>/loan/amortization?extra=&lump=&lump_month=&target_months=`. UI: 4 baseline stat cards
  (monthly payment, term, total interest, debt-free-by) + three inputs that debounce-refetch and render a
  green "Debt-free N months sooner · save ₹X interest" card, plus an **animated amortization chart**: per-month
  bars split principal (dark) + interest (amber) with a declining **balance line** (the endpoint returns the
  baseline AND scenario `schedule`). The chart redraws on every what-if — bars scale to the recurring payment
  (a one-time lump spike is clamped + marked "▲ lump", never crushes the others), the term shrinks, and the
  saved months show as a shaded "N mo saved" region on the right (x-extent stays the original term). Needs a
  tenure (prompts "Set term" → opens the edit-terms slide-over); diverging payments (< monthly interest) are
  flagged. **Framing:** a forward PROJECTION, labelled "projection · not the ledger" — Khata loans actually
  accrue interest + take manual principal repayments; this answers "what if I amortised it instead." (Closes
  the §10 EMI/amortization defer.)
- **2026-06-05 — Profile pictures (crop tool, server-side) + avatars across the asset page.** Replaced the
  old per-browser localStorage avatar hack with a real **server-side photo per user** (`users.avatar`, a
  cropped 256px JPEG data URL): so every member sees each contributor's face, and photos travel with backups.
  (1) **Crop tool** (Settings → avatar): pick a file → a circular crop overlay with **drag-to-pan + zoom
  slider**, rendered to a 256×256 canvas → `POST /api/auth/avatar`. Remove button clears it. (2) **Contributor
  tiles** show the photo (coloured initial fallback), **hover/click reveals a large clean version** in a
  floating popover; each person's colour rings their avatar and matches their share-bar segment. (3) **Share
  bar redesigned** — a clean proportional two-tone bar with NO cramped inline labels (a 19% slice no longer
  crushes text); names + % live in the rows below. (4) **Ledger rows** show the paying contributor's avatar
  inline (asset_state ledger gained `paid_by_avatar`; contributors gained `avatar`). (5) **Ledger edit** is now
  a single **✎ edit** toggle in the panel header → enters an edit mode (rows highlight + become clickable to
  edit), replacing the per-row ✎. Topbar avatar on detail pages is display-only and links to Settings to edit.
- **2026-06-05 — Avatars everywhere + killed the stale localStorage photo.** Follow-up to the above: the
  topbar avatar on **every** page now loads the current user's server avatar from `/api/auth/me` (and purges
  the old per-browser `khata_avatar` localStorage key, which was leaking a previous account's photo across
  logins on a shared browser — the reported bug). The **"Shared with" member list** (`sharing.js`, used on
  every detail page's Members panel) shows each member's avatar too (`list_members` gained `avatar`). So a
  contributor's photo now appears consistently wherever they're shown — topbar, contributors, ledger, members
  — and reflects the logged-in account, not a cached one. (Loan/chit ledger paid_by avatars still pending —
  those state dicts don't yet carry paid_by_avatar.)
- **2026-06-05 — Removed the asset "Recent pace" banner.** It extrapolated a monthly rate from the last 2–3
  inter-payment gaps; when payments were <1 day apart the `30.44/avgGapDays` factor exploded (saw ₹54+
  crore/mo), and the extrapolation was low-value for irregular asset buying regardless. An animated-trajectory
  replacement was tried and rejected (chart read as clutter, not insight). Removed entirely — the KPIs
  (paid/remaining/total), progress bar ("63% paid · 5 of 8 installments"), and the schedule panel (due dates)
  already carry the facts. `derivePace`/`renderTrajectory` deleted from asset-detail.html.
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
- **Loan amortization projection** — BUILT (see §9 "Loan repayment projection"): EMI + extra/lump/target
  what-ifs. (A side-by-side EMI-vs-bullet *comparison* view is still not built.)
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
- **Backup/restore**: in-app (Settings → Data) downloads/uploads a whole-instance JSON (upload = wipe + load
  verbatim; pre-restore snapshot auto-saved first); or operator CLI `scripts/backup.sh [DB] [DEST]` (online
  SQLite `.backup`, safe while live) + `scripts/restore.sh BACKUP [DB]` (file replace; stop the app first).
  Auto-saved snapshots land in `<db_dir>/backups/` (gitignored). Back up `khata_app.db` regularly — it's the
  only source of truth. **After restoring a backup taken on a DIFFERENT instance, rotate `KHATA_SECRET_KEY`**:
  sessions/bearer tokens signed by the old key stay validly signed and carry raw user ids, so a stale token
  could map onto a different (foreign) user that now owns that id.
- **Canonical local instance** (current): port **5057**, code from the `feat/landing-page` worktree,
  data in `khata_app.db`, secret persisted in `.env.app`, restart via `run-app.sh`. HTML is `no-store`
  (always fresh); static edits live on reload; Python edits need a restart. **Not yet** a reboot-surviving
  service (launchd) — add when wanted. Back up `khata_app.db` (only source of truth).
- **Production (Debian VM 192.168.50.14)** — now **Docker**, replacing the old systemd+gunicorn unit
  (systemd `khata` left `disabled`). Build source = **`main`** (owns the live DB's alembic head
  `fxsnapshot01`; do NOT deploy a feature branch — migration mismatch crash-loops). Repo-root
  `Dockerfile` (python:3.12-slim + gunicorn `-w 2 :5057`), `docker-entrypoint.sh` (`alembic upgrade
  head` → gunicorn), `docker-compose.yml` (`restart: always`, healthcheck, watchtower-disabled label).
  DB on a **bind mount** `~/khata/app/data/khata_app.db` (`KHATA_DATABASE_URL=sqlite:////data/...`) so
  rebuilds never touch data; env from `~/khata/app/.env.prod`. Deploy = rsync a clean `main` worktree
  (with the Docker files) → `~/khata/app`, then `docker compose up -d --build`. Ops: `docker ps`,
  `docker compose {up -d,restart,logs -f,down}`. Pre-Docker DB fallback kept at `~/khata/khata_app.db`.
- **App distribution (personal, free):** Khata installs three ways without the App Store —
  (1) a **PWA** of the web app (`/manifest.webmanifest` + `/sw.js`, injected by `nav.js`):
  Mac "Add to Dock", iOS "Add to Home Screen"; (2) the **Expo native iOS app** (`mobile/`)
  sideloaded via **SideStore** on a free Apple ID, auto re-signed over WiFi every ≤7 days —
  see `mobile/docs/build-ipa.md` + `mobile/docs/sidestore-setup.md`; (3) the web app in any
  browser. The native app points at `https://khata.npalakurla.com` (bearer-token auth).

## 12. Process going forward
**Every enhancement updates this doc** (§9 + the change log) in the same commit as the code — so a
from-scratch build reads here, not the app. Verify UI changes with the headless harness
(jsdom render + raw-HTML/CSS/mockup diff) before "done".

---

## Change log
- 2026-06-27 — Log-payment calculator + multi-currency input. Two additions to the Log payment slide-over (asset-detail.html, no backend changes): (1) **Calculator** — type any math expression (`50000+25000`, `2*85000`) in the amount field; live `= ₹X` preview as you type, blur evaluates and fills the result (safe: only digits/operators/parens pass). (2) **Multi-currency** — currency picker next to the amount (defaults to plan currency). Switch to a foreign currency (e.g. USD on an INR plan) for a live `≈ ₹X` FX preview using stored rates; on save, converts to plan currency and auto-prefixes the note with the original (`$1,000 USD — land payment Q2`). No rate → error pointing to Settings → FX rates.
- 2026-06-19 — Asset details. Assets gain seller & buyer (free text + optional Contact link),
  custom info rows + external links (JSON columns on `asset_purchases`), and document attachments
  (a third attachment parent `asset_plan_id`; video = a link, not an upload — keeps the one-file
  backup). Owner edits via `PATCH /api/plans/<id>/asset/meta`; asset docs upload owner-only,
  download plan-member. http(s)-only URLs; seller/buyer/fields/links scrubbed from public share
  links. Migration `as1assetmeta01`.
- 2026-06-19 — Loans By-contact view redesigned. Retired the hand-rolled Sankey (unreadable
  for a small loan book) for an editorial layout: a position band (100%-stacked exposure meter
  + Owed-to-you / You-owe / Net), ruled per-contact ledger rows (principal · interest/mo ·
  next-due, expandable to each person's loans), and a compact treemap breakdown (area =
  outstanding, click → scroll to the contact). Frontend-only (app.html); same
  /api/plans/loans/grouped data. No migration. (The endpoint still returns a now-unused `sankey`
  payload — harmless; client ignores it.)
- 2026-06-19 — Loans grouped by contact + Sankey. By-direction ↔ By-contact toggle on the Loans
  page: By-contact groups loans per person (contact name, else counterparty; same names merge),
  given/taken within, each with principal · expected interest/mo · next-month due (base currency).
  Hand-rolled SVG Sankey (Direction → Contact → Loan, weighted by outstanding) with a stacked-bar
  fallback on small screens. New read-only `GET /api/plans/loans/grouped` (owner-only) computes the
  aggregation + sankey server-side (reuses loan_state + fx). No migration.
- 2026-06-19 — Contacts + per-contact loan grouping. New Contacts section: a contact record
  (name/phone/email/address/notes/photo + document attachments via the attachments table) that
  loans link to (`loans.contact_id`, manual assign, SET NULL on delete). Per-contact rollup of
  principal + interest — per-currency subtotals plus a base-currency grand total. New `contacts`
  table (migration `ct1contact01`), contacts service + API, Contacts pages + loan contact picker.
  Owner-only; contact PII kept out of shared/public views.
- 2026-06-19 — Public read-only share links. Any plan (asset/loan/holding/chit/retirement) can be
  shared via a tokenized public URL (`/s/<token>`, no login) with expiry (7/30/90d) + revoke and a
  per-share summary|full (PII-redacted) scope; plus token-less Print and navigator.share "send".
  New `plan_shares` table (migration `sh1share01`), `sharing_links` service (recursive PII scrub),
  public blueprint `GET /api/public/<token>` (404/410), owner-only `POST/GET/DELETE /api/plans/<id>/shares`,
  standalone print-friendly `/s/<token>` page (CSP, robots:noindex).
- 2026-06-19 — Backfill historical loan payments. Loan detail can now mark past interest dues as paid/received (wording follows loan direction): a per-month button on each unpaid schedule row (interest = remaining expected, editable, + optional principal, dated in that month) and a bulk "mark through Month N" control. Backend: new `loans.backfill_loan_interest` + owner-only `POST /loan/backfill`; both record backdated `interest_payment` entries against the existing greedy interest pool — no schema change. Idempotent (paid months skipped).
- 2026-06-19 — Production VM containerized. Replaced systemd+gunicorn on the Debian box
  (192.168.50.14) with Docker: repo-root `Dockerfile` / `docker-entrypoint.sh` /
  `docker-compose.yml` / `.dockerignore`. gunicorn `-w 2 :5057`, `restart: always`, healthcheck,
  SQLite on a bind-mounted `data/` volume, env from `.env.prod`, watchtower opted out. systemd
  `khata` stopped + `disabled`. **Deploy source must be `main`** — the live DB's alembic head is
  `fxsnapshot01` (FX-snapshot, PR #52), which only `main` carries; deploying a feature branch
  crash-loops on `alembic upgrade head`. Ops now: `docker ps` / `docker compose up -d`. See §11.
- 2026-06-12 — Installable apps (free, no App Store). Added a PWA layer to the web app
  (`manifest.webmanifest` + `sw.js` served by Flask, tags + SW registered via `nav.js`) →
  installable on Mac and iOS home screen. The service worker is network-first everywhere
  (always fresh online; cache is offline fallback only). Prepared the existing Expo app for
  SideStore sideloading on a free Apple ID: `ios.bundleIdentifier` (`com.npalakurla.khata`),
  `supportsTablet`, `orientation: default`, prod `API_BASE`, and an iPad content-width cap
  in the shared `Screen` component. Two runbooks (`mobile/docs/build-ipa.md`,
  `sidestore-setup.md`) cover the owner-run build + install + weekly WiFi re-sign. Native
  OTA (`expo-updates`) is documented as future work, not built.
- 2026-06-12 — Loan-detail honors the global primary-currency preference. Previously the
  loan-detail page pinned its display to the loan's native currency (`BASE = plan.currency`)
  and the currency toggle was hidden — so an INR loan stayed ₹ even when the dashboard
  primary currency was USD. Now the page keeps `BASE` = the loan's native currency (for
  semantics: collateral-holding filter, per-entry fx editing, the `· INR` truth label) and
  adds a separate display layer: `DISP` = the user's `base_currency` preference, `FXR_MICRO`
  = the BASE→DISP rate (from `/api/fx-rates`; factor = DISP-per-BASE, inverting the stored
  rate when only the reverse is on file), and `conv(minor)`. The amount chokepoints
  (`amtSpan`, the gold "rate at loan time") convert native→display, so principal, interest,
  ledger, the repayment schedule incl. running-due/owed, glance, and collateral all follow
  the toggle. The **payoff projection panel stays native** — its inputs (`extra`/`lump`) feed
  native-currency server math. The currency toggle is re-enabled (same `/api/base-currency`
  POST + reload as the dashboard). No fx rate on file → graceful fallback to native. No
  backend change.
- 2026-06-12 — Loan running totals. `loan_state` schedule rows now carry `cum_due_minor`
  (cumulative unpaid interest through that month, net of payments), `principal_minor` (the
  month's opening principal), and `total_owed_minor` (principal + cumulative pending). The
  loan-detail repayment schedule shows a `running due … · owed …` line per month; the
  dashboard loans list shows `pending int … · owed …` per loan (from `interest_due_minor` /
  `total_minor`) and running section totals in the BORROWED / LENT OUT footers (summed in base
  currency). No new model, migration, or endpoint.
- 2026-06-11 — Plan Delete button added to asset, chit, holding, and retirement detail pages (loan-detail already had it). All five detail pages now show a ghost Delete button in the page header, visible to any viewer; `DELETE /api/plans/<id>` enforces owner-only (a member's click receives an error alert). Closes the gap that left restore-duplicated assets undeletable.
- 2026-06-11 — Restore is now replace (wipe + load), was merge. `POST /api/restore` wipes every backed-up
  table then loads verbatim (original ids preserved); re-importing a backup no longer duplicates plans.
  `backup_config`/`fx_refresh_state` left untouched; backups with no users rejected (400); operator
  re-authenticated by email — `logged_out: true` + session cleared if their account isn't in the backup.
  Settings page copy updated ("replaces everything" hint + confirm dialog); success handler redirects to `/`
  on `logged_out`; stats now use `users`/`plans`/`ledger_entries` keys (old `users_created`/`users_matched`
  gone). Restoring the same file twice is idempotent. Inconsistent backup rows (dangling FK / duplicate id,
  e.g. a hand-edited file) surface as `BackupError` → 400, not a 500; rollback leaves the instance untouched.
  Ops note added (§11): rotate `KHATA_SECRET_KEY` after restoring a foreign-instance backup.
- 2026-06-11 — Fix: `fx_live` sends a `User-Agent: khata-fx/1.0` header — frankfurter.dev sits behind
  Cloudflare, which 403s Python's default urllib UA, so every live fetch silently returned None on
  prod (caught post-deploy: refresh claim kept releasing, rate stayed manual).
- 2026-06-11 — FX rate snapshots: every ledger entry freezes its exchange rate at log time
  (`fx_rate_micro`/`fx_counter_currency`, migration `fxsnapshot01`), editable later (PATCH, 422 on
  bad rate, never re-opens confirmation). Live rates from frankfurter.app (`services/fx_live.py`,
  fallback chain explicit→live→Settings→NULL); hourly scheduler claims one daily USD/INR refresh
  atomically (`fx_refresh_state`); dashboard paid-to-date converts per-entry snapshot-first; admin
  `POST /api/admin/fx-backfill` for historical entries (prod write — manual, once, on explicit
  authorization). UI: fx line under ledger amounts (asset/loan/chit) via `assets/fx.js`, FX-rate
  field in the three edit forms, Settings hint notes the daily ECB refresh. Spec
  `docs/specs/2026-06-11-fx-snapshot-design.md`; full detail in §9.
- 2026-06-11 — Responsive pass (phone/tablet/desktop, evidence-first audit via headless Chrome at
  320/375/768/1440 across all 14 pages — zero horizontal overflow found; fixes confined to touch
  targets and micro-type). All tap-size fixes ship under `@media(pointer:coarse)` so desktop pointer
  layouts are untouched; phone type floors apply ≤640px (≤560px in-app). Changes: `assets/sharing.js`
  Add button gets `flex:none` (flex row squeezed it to 28px); `assets/ledger.css` gains coarse 44px
  min-heights for nav/footer links, ₹/$ toggle, `.btn`, brand links + `:where(...):focus-visible`
  outline + landing tag 11px floor; `settings.html` invite-row buttons were unstyled (selector
  mismatch `.acts .save` vs `.inv-link .save`) — selectors extended, backup checkbox 22px,
  coarse 44px block for backup-row/user-row actions; `loan-detail.html` Edit/Delete pills 44px coarse
  + pill/proof 11px floor; `assets/app.css` `.proof` (✎ edit-schedule) tap-area expanded via
  padding+negative margin (no layout shift) + micro-type floors (tag/pill/proof/rollbadge 11px);
  `join.html` + `welcome.html` footer/band-nav links 44px coarse + focus-visible on join. Round 2 (after
  re-audit): sharing.js Add button was fully unstyled on detail pages (no `.btn` rule outside ledger.css)
  — now styled inline (primary pill) + coarse `button.btn` 44px in app.css; landing `.nav-links a` +
  `a.link` get coarse `min-width:44px`; sub-11px stragglers floored to 11px ≤560px in `app.html`,
  `create-plan.html`, `holding-detail.html`, `chit-detail.html`, `retirement-detail.html` (page styles
  win over app.css, so floors live per-page) and four 10px JS `cssText` captions bumped to 11px
  (app.html ×2, loan-detail.html ×2). Settings backup checkbox stays 22px — it sits inside a 44px-min
  `.bk-toggle` label, which is the tap target. Verified headless: zero overflow at 320/375/768/1440 on
  all 14 pages, all touch targets ≥30px (44px coarse minimums), type floor 11px; 288 tests pass. No
  logic or desktop-visual changes beyond the 1px caption bump.
- 2026-06-11 — Invite links (Phase C of admin/backup work — copy-link flow, no SMTP). An admin generates a
  signed join link for an email (`POST /api/admin/invites` → `/join?token=…`, 7-day expiry) and shares it
  however they like; Google sign-in can't send mail (restricted `gmail.send` scope), so no email is sent
  from the server. The link opens `join.html` (served at `GET /join`): it peeks the token (`GET
  /api/auth/invite`), shows the bound email, and the recipient sets a name + password — or Continue with
  Google — via `POST /api/auth/accept-invite` (email is taken from the signed token, not the client; existing
  email → 409 "sign in instead"). Stateless signed tokens reuse `itsdangerous` (`tokens.issue_invite`/
  `read_invite`, salt `khata-invite-v1`) — no DB table. Settings → Admin panel gains an "Invite someone" box
  (email → Create invite link → Copy). Note: registration is still open; invites are a pre-addressed
  convenience, not (yet) an access gate. 8 new tests.
- 2026-06-11 — Automatic scheduled backups (Phase B of admin/backup work). New `backup_config` singleton
  (migration `df9backup01`) + in-app **APScheduler** (`khata/scheduler.py`, hourly tick, env-gated by
  `KHATA_ENABLE_SCHEDULER=1` so tests never spawn threads). Backups are whole-instance JSON snapshots
  written to `backups/auto-<stamp>.json` (0o600), pruned to `retention` (default 14). `services/backup_store.py`:
  write/prune/list + a pure `is_due`/`claim_threshold` decision and an atomic `claim_due` (UPDATE on
  `last_run_at`) so the two gunicorn workers never produce a double backup. Admin API: `GET/POST
  /api/admin/backup-config` (enabled · daily/weekly · hour 0–23 · retention 1–365), `POST /api/admin/backup-run`
  (manual), `GET/DELETE /api/admin/backups/<name>` (download/delete, `auto-*.json` name allowlist — no path
  traversal). Settings → Data panel gains the **Automatic backups** controls (toggle, frequency, hour,
  retention, last-run/status, Back-up-now, list with download/delete). New dep `APScheduler==3.10.4`.
  Phase C (email invites) still deferred.
- 2026-06-11 — Topbar avatar → profile dropdown. The account avatar in the topbar now opens a standard
  profile menu (signed-in name + email, Settings link, Log out) instead of jumping straight to Settings.
  Shared `static/assets/profile-menu.js` (`mountProfileMenu()`, K4-safe; outside-click/Escape close; hides
  the legacy camera-upload overlay and fills the initial). Replaced the per-page inline avatar IIFE across
  8 app pages (dashboard + holdings + analysis + 5 detail pages); Settings page keeps its in-place photo
  uploader. Dropdown styles in `app.css` (`.pmenu*`).
- 2026-06-11 — Admin role + user management (Phase A of admin/backup work). New `users.is_admin` +
  `users.disabled` (migration `de8admin01`; first user bootstrapped admin). Admin-only `/api/admin`
  blueprint: list users, promote/demote admin, disable/re-enable login, reset a user's password,
  delete a user + cascade their owned plans. Hard invariant in `services/admin.py`: always keep ≥1
  enabled admin (demote/disable/delete of the last admin is refused); can't disable/delete yourself.
  Disabled accounts are blocked at login (`403 account_disabled`) and their live session stops
  resolving (`current_user`). The legacy backup "operator" gate now resolves to `is_admin OR legacy`
  so admins inherit backup/restore. Settings → **Admin · users** panel (shown to admins) with avatars,
  badges, and per-user actions (typed-DELETE confirm). `/api/auth/me` + `_user_json` expose `is_admin`.
  Email-invite (Phase C) intentionally deferred — Google sign-in can't send mail (needs the restricted
  `gmail.send` scope), so invites will be a copy-a-link flow, optional Gmail-SMTP auto-send later.
- 2026-06-11 — Proof attachments mobile polish: the "+ Add file" / "📷 Take photo" controls were cramped
  on phones — now equal-width flex buttons on their own full-width row with 44–46px touch targets, wrapping
  to stacked full-width when too narrow (`app.css` `.att-add`/`.att-btn` + a `max-width:560px` block).
- 2026-06-11 — Ledger-entry attachments (supporting proof): upload photos / PDFs / Office docs or
  **take a photo** (rear camera on phones) against any ledger entry, in the entry-edit drawer of the
  asset / loan / chit detail pages. New `attachments` table (blob bytes in the DB; mime by magic bytes,
  not extension; 25 MB cap; client-side image downscale drops EXIF/GPS). API: `attachments` blueprint —
  `GET/POST /api/plans/<pid>/entries/<eid>/attachments`, `GET/DELETE /api/attachments/<id>` (served with
  the stored mime, images/PDF inline, membership-gated, `nosniff`). Lights the existing `▣ proof` tag
  (`has_proof = proof_ref OR attachments`) + `attachment_count`. Backup serializer base64s the blob so the
  one-file JSON backup still round-trips (verified). Shared `static/assets/attach.js` (`mountAttachments`,
  K4-safe createElement render). Migration `dd7attach01`. Finishes the long-promised "attach the receipt,
  screenshot, or chat — timestamped proof" from the marketing page.
- 2026-06-11 — Production deploy runbook (`scripts/deploy-prod.sh`): one-shot SSH deploy to the prod
  box (Debian 12). rsync code from a clean `main` checkout → `~/khata/app`; build venv + install deps;
  carry real data via a consistent `sqlite3 .backup` snapshot (**first run only — never overwrites an
  existing prod DB**); write `~/khata/.env.prod` (secret + Google id, chmod 600); `alembic upgrade head`;
  gunicorn smoke-boot; emit a systemd unit. Debian gotcha: box ships no `python3-venv`/`pip` and apt was
  unavailable, so the venv is created `--without-pip` and pip is bootstrapped via `get-pip.py` (no sudo).
  Live at `https://khata.npalakurla.com` behind the user's nginx TLS proxy (X-Forwarded-Proto https);
  `KHATA_SECURE_COOKIES=1` set only after the proxy was confirmed live. systemd `enable --now` (survives
  reboot, `Restart=always`). The marketing page (below) ships in the same deploy at `/welcome`.
- 2026-06-10 — Marketing landing page served by the app at `GET /welcome`
  (`src/khata/static/welcome.html`, self-contained — no build step; root `/` sign-in unchanged).
  "Bound ledger" editorial design (Fraunces/Newsreader/Spline Sans Mono; ink/ivory/sindoor/gold).
  Scroll-scrubbed 3D hero: 1,300 instanced ledger entries chaos→ruled-grid→gold sum beam with
  net-worth count-up; three.js (lazy ESM) + GSAP ScrollTrigger + Lenis via SRI-pinned CDN.
  prefers-reduced-motion static fallback, mobile instance/DPR cuts, headless-verified (0 console
  errors, no h-overflow, 60fps mobile-viewport). Nav/CTA "Sign in" links to `/`. Build dashboard
  convention in `_build-dashboard/` (status JSON + self-polling dashboard + serve script, :4178).
- 2026-06-09 — Mobile Phase 6 native features. Settings now has avatar pick→square-crop→
  256px JPEG (expo-image-picker + image-manipulator, kept <200KB for the `/api/auth/avatar`
  cap) with display + remove, and an operator-only Backup & restore card (export → share
  sheet via expo-file-system + expo-sharing; restore → expo-document-picker → POST /api/restore).
  Gated on `/api/auth/me` `is_operator` (now surfaced through AuthContext). No backend changes.
- 2026-06-09 — Expo React Native iPhone app (`mobile/`, web-to-mobile Phases 1–5). Native
  client over the existing REST API: bearer-token auth in Keychain (expo-secure-store), email/
  password + Google sign-in, 5 bottom tabs (dashboard, holdings, net worth, hold-vs-sell
  analysis, settings), generic plan-detail screen for all 5 plan types, and a create-plan modal.
  TanStack Query for data; theme tokens + INR/USD money formatting ported verbatim from the web
  CSS/JS for parity. `tsc` clean, iOS bundle exports clean. Phase 6 (avatar/backup native pickers)
  deferred to v1.1. The Flask backend is unchanged beyond the Phase-0 token/CORS work below.
- 2026-06-09 — Mobile bearer-token auth + API CORS (web-to-mobile Phase 0). `current_user()`
  now accepts `Authorization: Bearer <token>` in addition to the session cookie, so the whole
  API works for a native client unchanged. login/register/google return a stateless
  `itsdangerous`-signed token (new `src/khata/tokens.py`, 30-day expiry, no DB table). `/api/*`
  gets permissive CORS (wildcard origin, OPTIONS→204) via `after_request`/`before_request` in
  `__init__.py` — no flask-cors dep. Web cookie auth untouched. Groundwork for the Expo iPhone
  app (plan: docs/web-to-mobile/2026-06-09-web-to-mobile-plan.md). 5 new tests, 251 total green.
- 2026-06-07 — Enabled Google Sign-In (already built). Set KHATA_GOOGLE_CLIENT_ID to
  reveal the button + /api/auth/google. New KHATA_SECURE_COOKIES=1 flag: when behind an
  HTTPS reverse proxy, applies ProxyFix (trust X-Forwarded-Proto/Host) + marks the
  session cookie Secure/HttpOnly/SameSite=Lax. Runbook: docs/google-signin-setup.md.
- 2026-06-07 — Loan fees + interest backfill. New `fee` loan entry kind (direction follows
  the loan: out on a taken loan, in on a given one); `loan_state.fees_paid_minor` surfaces
  total fees, shown in the Glance panel. Create-loan form has a "Processing / upfront fee"
  field (logs a dated fee entry at start). Interest paid/received for past months already
  worked via Add-entry + the "When" date (the month schedule marks paid months); now the
  Interest entry option + ledger row read "Interest paid" on a taken loan / "Interest
  received" on a given one. Asset funding-link tag (`↗ loan`) is navigable only when the
  viewer can open that loan (`asset_state.ledger[].funding_plan_accessible`); a contributor
  who isn't on the loan sees a plain provenance tag, not a dead link.
- 2026-06-06 — QA hardening pass (multi-currency + correctness). Currency: `fx.get_rate`
  inverse-rate fallback + `GET /api/fx-rates`; `dashboard.net_position` and the dashboard
  UI convert each plan to base and surface an `unconverted` per-currency bucket (net
  position no longer reads "$0" when no rate is set — it shows the real ₹ figure with a
  "set a rate" nudge); `amtSpan` renders every amount in its OWN currency (no ₹-as-$
  mislabelling); FX editor defaults the quote to the non-base currency and lists existing
  rates. Correctness: `money.py` returns 400 (not 500) on overflow/`1e1000`; loan glance
  monthly interest ÷10000 for monthly-rate loans (was 12× low); holdings hold-vs-sell no
  longer double-scales 100×; `_emi` rounds up so the schedule never overshoots tenure;
  inline-gold loans report `secured` and render the Collateral panel (LTV bar). UX:
  inert currency toggle hidden on detail pages; asset/retirement show a not-found card
  (not a silent bounce); backup/restore panel operator-only (`/api/auth/me.is_operator`);
  create-plan rejects empty name / unknown type. Deferred: per-round chit prize→"your pay"
  (needs a per-round taker model) and the ₹-fractional chit subscription display.
- 2026-06-06 — Merged `main` into `feat/phase6-fidelity` to reconcile two parallel UI tracks that diverged at e36509d (Phase 5). Both rewrote the same static screens from the same mockups; file-by-file comparison showed `main` (the feature track) is a superset of the phase6 fidelity pass on the identical editorial design system — phase6 carried no render function `main` lacked — so `main` is canonical for every screen. Backend merged clean. One phase6-correct fix kept: app.html `renderFeatured` no longer dumps the whole asset ledger inline on the dashboard (it stacked into an endless wall on mobile); the per-asset ledger lives on /asset/:id. Restored real Records nav (Features/Analysis). 227 tests pass; all reconciled routes verified zero JS throws (jsdom).
- 2026-06-06 — Mobile dashboard fixes: Net-position hero card was blank on narrow screens (decorative ::after radial painted over the text → gave it z-index above the radial); loans-list interest column now actually hides on phones (was beaten by inline display:flex → !important); topbar hides the currency toggle on phones so 'Log payment' fits without wrapping.
- 2026-06-06 — Landing page mobile cleanup: nav reduced to brand + Sign in (section anchors + currency toggle desktop-only), section padding 94px→52px on phones, hero min-height dropped, type scaled, grids stack. Professional on iPhone-class widths.
- 2026-06-06 — Responsive: off-canvas sidebar drawer + hamburger (nav.js), responsive topbar/padding, stacked KPIs/stats on phones, loans interest column hidden on phones. App usable on tablet + mobile.
- 2026-06-06 — Cross-currency funding link: a contribution funded by a loan in a DIFFERENT currency now renders in its own currency on the loan's "Deployed into" (per-currency totals, no nonsensical cross-currency sum; row flags the currency). `loan_state.deployed[].currency` + `deployed_totals`.
- 2026-06-06 — A plan contributor can now edit/delete their OWN ledger entries (was owner-only → 403 'forbidden' for a member editing their contribution). Owner still required to re-attribute an entry to someone else. Missing entry now → 404 (was 400).
- 2026-06-06 — Cross-plan funding link: an asset contribution can point to the loan it came from (`funding_plan_id`); asset ledger shows “↗ loan”, loan shows a “Deployed into” panel. Full loan→asset→payoff chain. Migration `cc6fundlink01`.
- 2026-06-06 — Assets list enriched like loans: row meta shows total · schedule/ad-hoc · joint contributors, right side shows amount paid + % progress + amount left (fetched per row). No more bare "1 Acre · INR".
- 2026-06-06 — Fix: loan rate label respects interest_type — a monthly-interest loan now reads "3%/mo" not "3%/yr" (was hardcoded /yr in the list meta, loan-detail glance, and compare table).
- 2026-06-06 — Loans list shows monthly interest cashflow: per-row interest/mo (− you pay on borrowed, + you earn on lent), group subtotals, and a "Net interest / month" footer (lent earnings − borrowed cost) telling you if you're net ahead or paying out. Client-only (app.html, monthlyInterestMinor).
- 2026-06-06 — Loans list splits Borrowed (you owe) vs Lent out (owed to you) — two sections with colour-coded headers + live subtotals; meta reads "N borrowed · M lent". Debt and receivables no longer lumped.
- 2026-06-06 — Fix: editing a gold loan's weight/rate now re-derives the collateral value (the on-open 'value touched' guard was blocking recompute, leaving a stale value → the 1000% LTV). A value you type after still sticks.
- 2026-06-06 — Gold LTV sanity guard: LTV >100% (impossible) flagged as an error everywhere — dashboard list "⚠ LTV NN%", loan-detail glance "⚠ NN%" + explainer row, and a live LTV hint in edit-terms as you type. Amber 75–100%, green ≤60%.
- 2026-06-06 — Plan-list rows differentiate (esp. loans): meta line (Gold · from SBI · 7.5%/yr), category chip, + outstanding amount and LTV fetched per loan row — two same-named gold loans now read apart before opening. Client-only (app.html planMeta).
- 2026-06-06 — Gold-loan collateral: weight/rate/market-value inputs on create + edit (shown for kind=gold, value auto-computed), shown in loan-detail glance with loan-to-value. `loans.collateral_*` cols + migration `cb5goldcoll01`, `loan_state.gold_collateral`.
- 2026-06-06 — Loan category (`loans.kind`: personal/gold/home/vehicle/education/business/other), picked at create + editable. loan-detail shows a Type row and a meaningful Security line (gold→"secured · gold" etc.) instead of bare "unsecured". Migration `ca4loankind01`.
- 2026-06-05 — Loan shop-around comparison: loan-detail "Compare lenders" panel — current loan vs user offers ranked by total cost + fee-inclusive effective APR (exposes low-rate/high-fee loans). `loans.compare_offers`, `_apr_bps` (IRR), `POST /api/plans/<id>/loan/compare`.
- 2026-06-05 — Loan repayment projection: loan-detail "Repayment plan" panel — EMI/total-interest/payoff baseline + extra-per-month / lump-sum / target-month what-ifs showing months & interest saved, plus an animated amortization chart (principal+interest bars + balance line) that redraws per scenario with a "N mo saved" region. `GET /api/plans/<id>/loan/amortization` (returns baseline + scenario schedules), `loans.amortize` (integer math, tested).
- 2026-06-05 — Avatars everywhere: topbar on every page loads the server avatar (purges stale localStorage that leaked a prior account's photo across logins — reported bug); "Shared with" member lists show avatars (`list_members.avatar`).
- 2026-06-05 — Asset ledger: each row shows its share of the plan total as a quiet "X% of total" line under the amount (right-aligned, muted; "<1% of total" for tiny entries). Client-side, no API change.
- 2026-06-05 — Profile pictures: server-side `users.avatar` + crop tool (drag/zoom) in Settings; contributor tiles + ledger rows show avatars (hover reveals full photo); contributors share bar redesigned (no cramped labels); ledger edit moved to a single header toggle (was per-row). `POST /api/auth/avatar`, asset_state avatar fields, migration c9a3avatar01. Also fixed a TZ-flaky secured-loan test (explicit occurred_at).
- 2026-06-05 — Asset detail: removed the broken "Recent pace" banner (₹-crore explosion on sub-day gaps, low-value extrapolation). KPIs + progress bar + schedule already carry the facts.
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

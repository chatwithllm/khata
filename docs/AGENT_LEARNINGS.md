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

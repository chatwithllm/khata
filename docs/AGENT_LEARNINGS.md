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

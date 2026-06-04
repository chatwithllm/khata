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

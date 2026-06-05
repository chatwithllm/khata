"""Whole-instance backup / restore.

Backup = a versioned JSON snapshot of every table (export_all). Restore = a MERGE
(import_merge): users are matched by email (existing reused, missing created), and all
plans + their children are inserted as NEW rows with their foreign keys remapped to the
target instance's ids. Restoring onto a non-empty instance ADDS on top — re-importing the
same file duplicates plans (no natural key); callers should warn the user.

The raw-SQLite CLI path (scripts/backup.sh / restore.sh) is the exact-replace alternative.
"""
from datetime import datetime, date, timezone

from sqlalchemy import select, inspect
from sqlalchemy import DateTime, Date
from sqlalchemy.orm import Session

from ..models import (User, Plan, AssetPurchase, Loan, Holding, Chit, Retirement,
                      Installment, LedgerEntry, PlanMembership, FxRate)

BACKUP_VERSION = 1

# Export order = FK dependency order (parents before children).
EXPORT_MODELS = [User, Plan, AssetPurchase, Loan, Holding, Chit, Retirement,
                 Installment, LedgerEntry, PlanMembership, FxRate]

# Plan sub-tables keyed 1:1 by plan_id (no own surrogate id).
PLAN_SUBTABLES = [("asset_purchases", AssetPurchase), ("loans", Loan),
                  ("holdings", Holding), ("chits", Chit), ("retirements", Retirement)]


class BackupError(Exception):
    pass


def _ser(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _row(obj) -> dict:
    # NB: this intentionally includes User.password_hash. A whole-instance backup must be
    # able to recreate working logins on a restored machine (there is no email/reset flow,
    # so stripping the hash would permanently lock every user out). The hash is a one-way
    # hash, the CLI raw-.db backup contains the same bytes, and access to this export is
    # gated to the instance operator (api/backup.py:_require_operator) with 0o600 files.
    cols = inspect(obj.__class__).columns.keys()
    return {c: _ser(getattr(obj, c)) for c in cols}


def _parse(model, raw: dict) -> dict:
    """Coerce a serialized row back into column-typed Python values, dropping any
    keys the current schema doesn't have (forward/backward compatibility)."""
    cols = inspect(model).columns
    out = {}
    for k, v in raw.items():
        if k not in cols:
            continue
        if v is not None:
            t = cols[k].type
            if isinstance(t, DateTime):
                v = datetime.fromisoformat(v)
            elif isinstance(t, Date):
                v = date.fromisoformat(v)
        out[k] = v
    return out


def export_all(session: Session) -> dict:
    """Serialize every table to a single JSON-able dict."""
    data = {"version": BACKUP_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tables": {}}
    for model in EXPORT_MODELS:
        rows = list(session.scalars(select(model)))
        data["tables"][model.__tablename__] = [_row(r) for r in rows]
    return data


def import_merge(session: Session, data: dict) -> dict:
    """Merge a backup into the current instance. Users match by email; everything else
    is inserted fresh with remapped foreign keys. Returns per-table stats."""
    if not isinstance(data, dict) or "tables" not in data:
        raise BackupError("not a Khata backup file")
    if data.get("version") != BACKUP_VERSION:
        raise BackupError(f"unsupported backup version: {data.get('version')!r}")
    t = data["tables"]
    stats = {"users_created": 0, "users_matched": 0, "plans": 0, "asset_purchases": 0,
             "loans": 0, "holdings": 0, "chits": 0, "retirements": 0,
             "installments": 0, "ledger_entries": 0, "memberships": 0, "fx_rates": 0}

    # --- users: match by email, reuse or create ---
    user_map: dict[int, int] = {}
    for u in t.get("users", []):
        email = (u.get("email") or "").strip().lower()
        existing = session.scalar(select(User).where(User.email == email)) if email else None
        if existing is not None:
            user_map[u["id"]] = existing.id
            stats["users_matched"] += 1
        else:
            f = _parse(User, u); f.pop("id", None)
            nu = User(**f); session.add(nu); session.flush()
            user_map[u["id"]] = nu.id
            stats["users_created"] += 1

    # --- plans: insert fresh, remap owner ---
    plan_map: dict[int, int] = {}
    for p in t.get("plans", []):
        f = _parse(Plan, p); old = f.pop("id")
        f["owner_user_id"] = user_map.get(f.get("owner_user_id"))
        if f["owner_user_id"] is None:
            continue  # orphan plan (owner not in backup) — skip rather than break FK
        np = Plan(**f); session.add(np); session.flush()
        plan_map[old] = np.id
        stats["plans"] += 1

    # --- 1:1 plan sub-tables (all plans now exist, so collateral refs remap cleanly) ---
    for tbl, model in PLAN_SUBTABLES:
        for r in t.get(tbl, []):
            f = _parse(model, r)
            f["plan_id"] = plan_map.get(f.get("plan_id"))
            if f["plan_id"] is None:
                continue
            if tbl == "loans" and f.get("collateral_plan_id") is not None:
                f["collateral_plan_id"] = plan_map.get(f["collateral_plan_id"])
            session.add(model(**f)); stats[tbl] += 1
        session.flush()

    # --- installments ---
    for r in t.get("installments", []):
        f = _parse(Installment, r); f.pop("id", None)
        f["plan_id"] = plan_map.get(f.get("plan_id"))
        if f["plan_id"] is None:
            continue
        session.add(Installment(**f)); stats["installments"] += 1

    # --- ledger entries ---
    for r in t.get("ledger_entries", []):
        f = _parse(LedgerEntry, r); f.pop("id", None)
        f["plan_id"] = plan_map.get(f.get("plan_id"))
        f["logged_by_user_id"] = user_map.get(f.get("logged_by_user_id"))
        if f["plan_id"] is None or f["logged_by_user_id"] is None:
            continue
        session.add(LedgerEntry(**f)); stats["ledger_entries"] += 1

    # --- memberships (plans are new, so no (plan,user) collision) ---
    for r in t.get("plan_memberships", []):
        f = _parse(PlanMembership, r); f.pop("id", None)
        f["plan_id"] = plan_map.get(f.get("plan_id"))
        f["user_id"] = user_map.get(f.get("user_id"))
        if f["plan_id"] is None or f["user_id"] is None:
            continue
        session.add(PlanMembership(**f)); stats["memberships"] += 1

    # --- fx_rates: global; dedup by (base, quote, as_of) so repeat imports don't pile up ---
    for r in t.get("fx_rates", []):
        f = _parse(FxRate, r); f.pop("id", None)
        dup = session.scalar(select(FxRate).where(
            FxRate.base_currency == f.get("base_currency"),
            FxRate.quote_currency == f.get("quote_currency"),
            FxRate.as_of == f.get("as_of")))
        if dup is not None:
            continue
        session.add(FxRate(**f)); stats["fx_rates"] += 1

    session.flush()
    return stats

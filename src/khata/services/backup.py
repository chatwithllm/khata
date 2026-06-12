"""Whole-instance backup / restore.

Backup = a versioned JSON snapshot of every table (export_all). Restore = a REPLACE
(import_replace): every backed-up table is wiped, then the backup's rows are inserted
verbatim — original ids preserved (tables are empty, so nothing needs remapping, and
stale session cookies / bearer tokens keep pointing at the same person when the backup
came from this instance). Restoring the same file twice is idempotent.

Operational state stays untouched: backup_config and fx_refresh_state are not part of
backup files and are never wiped.

The raw-SQLite CLI path (scripts/backup.sh / restore.sh) is the offline alternative.
"""
import base64
from datetime import datetime, date, timezone

from sqlalchemy import select, inspect, delete
from sqlalchemy import DateTime, Date, LargeBinary
from sqlalchemy.orm import Session

from ..models import (User, Plan, AssetPurchase, Loan, Holding, Chit, Retirement,
                      Installment, LedgerEntry, PlanMembership, FxRate, Attachment)

BACKUP_VERSION = 1

# Export order = FK dependency order (parents before children). Attachment follows
# LedgerEntry (its parent) so a restore can remap entry ids before inserting blobs.
EXPORT_MODELS = [User, Plan, AssetPurchase, Loan, Holding, Chit, Retirement,
                 Installment, LedgerEntry, Attachment, PlanMembership, FxRate]


class BackupError(Exception):
    pass


def _ser(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return base64.b64encode(v).decode("ascii")   # blobs (attachment bytes)
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
            elif isinstance(t, LargeBinary):
                v = base64.b64decode(v)               # blobs (attachment bytes)
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


def import_replace(session: Session, data: dict) -> dict:
    """Wipe ALL existing data, then load the backup verbatim (ids preserved).
    Returns per-table insert counts keyed by table name. The caller owns the
    transaction — any failure raises and a rollback leaves the instance untouched."""
    if not isinstance(data, dict) or "tables" not in data:
        raise BackupError("not a Khata backup file")
    if data.get("version") != BACKUP_VERSION:
        raise BackupError(f"unsupported backup version: {data.get('version')!r}")
    t = data["tables"]
    if not t.get("users"):
        raise BackupError("backup contains no users — restoring it would brick every login")

    # Wipe children before parents (reverse of the FK-ordered EXPORT_MODELS).
    # Explicit order — never trust relationship cascade config for this.
    for model in reversed(EXPORT_MODELS):
        session.execute(delete(model))
    session.flush()

    # Insert verbatim, parents first. _parse keeps the "id" column, so every row
    # lands with the id it had when the backup was taken.
    stats: dict[str, int] = {}
    for model in EXPORT_MODELS:
        n = 0
        for raw in t.get(model.__tablename__, []):
            session.add(model(**_parse(model, raw)))
            n += 1
        session.flush()
        stats[model.__tablename__] = n
    return stats

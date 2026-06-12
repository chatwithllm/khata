"""Admin API — user management (admin-only).

Gated by `services.admin.is_admin`. All routes 403 for non-admins. The service layer
enforces the "always keep one enabled admin" invariant and the no-self-footgun rules.
"""
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin

from flask import Blueprint, Response, current_app, g, jsonify, request
from sqlalchemy import select

from ..models import LedgerEntry, User
from ..services import admin, backup_store
from ..services import fx, fx_live
from ..services.admin import AdminError
from ..tokens import issue_invite
from .auth import current_user

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _require_admin():
    user = current_user()
    if user is None:
        return None, (jsonify(error="unauthenticated"), 401)
    if not admin.is_admin(user):
        return None, (jsonify(error="forbidden", detail="admin only"), 403)
    return user, None


@bp.get("/users")
def list_users():
    _, err = _require_admin()
    if err:
        return err
    return jsonify(users=admin.list_users(g.db)), 200


@bp.post("/users/<int:user_id>/disable")
def set_disabled(user_id):
    actor, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        u = admin.set_disabled(g.db, actor=actor, user_id=user_id, disabled=bool(data.get("disabled")))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, disabled=u.disabled), 200


@bp.post("/users/<int:user_id>/admin")
def set_admin(user_id):
    actor, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        u = admin.set_admin(g.db, actor=actor, user_id=user_id, make_admin=bool(data.get("is_admin")))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, is_admin=u.is_admin), 200


@bp.post("/users/<int:user_id>/reset-password")
def reset_password(user_id):
    _, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        admin.reset_password(g.db, user_id=user_id, new_password=data.get("password", ""))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True), 200


@bp.post("/invites")
def create_invite(user_id=None):
    """Mint a signed join link for an email. The admin shares the link however they like
    (no email is sent from the server). The recipient opens it and sets up their account."""
    _, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(error="invalid", detail="enter a valid email"), 400
    existing = g.db.query(User).filter(User.email == email).first()
    token = issue_invite(current_app.config["SECRET_KEY"], email)
    join_url = urljoin(request.url_root, "join") + "?token=" + token
    return jsonify(email=email, token=token, join_url=join_url, expires_in_days=7,
                   already_member=existing is not None), 200


@bp.delete("/users/<int:user_id>")
def delete_user(user_id):
    actor, err = _require_admin()
    if err:
        return err
    try:
        stats = admin.delete_user(g.db, actor=actor, user_id=user_id)
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, **stats), 200


# ── automatic backups ──

def _config_json(cfg) -> dict:
    return {"enabled": cfg.enabled, "frequency": cfg.frequency, "hour": cfg.hour,
            "retention": cfg.retention,
            "last_run_at": cfg.last_run_at.isoformat() if cfg.last_run_at else None,
            "last_status": cfg.last_status,
            "scheduler_running": os.environ.get("KHATA_ENABLE_SCHEDULER") == "1"}


def _db_url():
    return current_app.config["KHATA"].database_url


@bp.get("/backup-config")
def backup_config():
    _, err = _require_admin()
    if err:
        return err
    cfg = backup_store.get_config(g.db)
    g.db.commit()
    return jsonify(config=_config_json(cfg),
                   backups=backup_store.list_backups(backup_store.backups_dir(_db_url()))), 200


@bp.post("/backup-config")
def update_backup_config():
    _, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    cfg = backup_store.get_config(g.db)
    if "enabled" in data:
        cfg.enabled = bool(data["enabled"])
    if "frequency" in data:
        if data["frequency"] not in ("daily", "weekly"):
            return jsonify(error="invalid", detail="frequency must be daily or weekly"), 400
        cfg.frequency = data["frequency"]
    if "hour" in data:
        try:
            h = int(data["hour"])
        except (TypeError, ValueError):
            return jsonify(error="invalid", detail="hour must be 0-23"), 400
        if not 0 <= h <= 23:
            return jsonify(error="invalid", detail="hour must be 0-23"), 400
        cfg.hour = h
    if "retention" in data:
        try:
            r = int(data["retention"])
        except (TypeError, ValueError):
            return jsonify(error="invalid", detail="retention must be 1-365"), 400
        if not 1 <= r <= 365:
            return jsonify(error="invalid", detail="retention must be 1-365"), 400
        cfg.retention = r
    g.db.commit()
    return jsonify(config=_config_json(cfg)), 200


@bp.post("/backup-run")
def backup_run_now():
    _, err = _require_admin()
    if err:
        return err
    cfg = backup_store.get_config(g.db)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        res = backup_store.run_backup(g.db, database_url=_db_url(), retention=cfg.retention, stamp=stamp)
        cfg.last_run_at = datetime.now()
        cfg.last_status = f"ok · {res['filename']} (manual)"
        g.db.commit()
    except Exception as e:
        g.db.rollback()
        return jsonify(error="backup_failed", detail=str(e)), 500
    return jsonify(ok=True, **res), 201


@bp.get("/backups/<name>")
def download_backup(name):
    _, err = _require_admin()
    if err:
        return err
    safe = backup_store.safe_backup_name(name)
    if safe is None:
        return jsonify(error="invalid", detail="bad backup name"), 400
    directory = backup_store.backups_dir(_db_url())
    path = os.path.join(directory, safe)
    if not os.path.isfile(path):
        return jsonify(error="not_found"), 404
    with open(path, "rb") as fh:
        body = fh.read()
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Cache-Control": "no-store",
    })


@bp.delete("/backups/<name>")
def delete_backup(name):
    _, err = _require_admin()
    if err:
        return err
    safe = backup_store.safe_backup_name(name)
    if safe is None:
        return jsonify(error="invalid", detail="bad backup name"), 400
    path = os.path.join(backup_store.backups_dir(_db_url()), safe)
    if not os.path.isfile(path):
        return jsonify(error="not_found"), 404
    os.remove(path)
    return jsonify(ok=True), 200


@bp.post("/fx-backfill")
def fx_backfill():
    """One-time idempotent FX backfill: stamp every NULL-rate ledger entry with
    the frankfurter rate of its occurred_at date (weekend → nearest prior
    business day). PROD DB WRITE — run manually, once, with explicit user
    authorization (spec §7). Safe to re-run: non-NULL entries are skipped."""
    _, err = _require_admin()
    if err:
        return err
    skipped = len(g.db.scalars(
        select(LedgerEntry.id).where(LedgerEntry.fx_rate_micro.is_not(None))).all())
    entries = g.db.scalars(
        select(LedgerEntry).where(LedgerEntry.fx_rate_micro.is_(None))).all()
    if not entries:
        return jsonify(filled=0, skipped=skipped, no_rate=0), 200
    days = sorted(e.occurred_at.date() for e in entries)
    # ONE range call: frankfurter base=USD → INR-per-USD per business day
    inr_per_usd = fx_live.fetch_range(days[0], days[-1], "USD", "INR")
    micro2 = fx_live.MICRO * fx_live.MICRO
    filled = no_rate = 0
    for e in entries:
        rate = fx_live.rate_for_date(inr_per_usd, e.occurred_at.date())
        if not rate or e.currency not in ("INR", "USD"):
            no_rate += 1
            continue
        if e.currency == "USD":
            e.fx_rate_micro = rate                      # counter INR-per-USD, direct
        else:
            # INR entry → counter USD-per-INR = inverse, exact Decimal
            e.fx_rate_micro = int((Decimal(micro2) / rate).quantize(
                Decimal(1), rounding=ROUND_HALF_UP))
        e.fx_counter_currency = fx.counter_currency_for(e.currency)
        filled += 1
    g.db.commit()
    return jsonify(filled=filled, skipped=skipped, no_rate=no_rate), 200

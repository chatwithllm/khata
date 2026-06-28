"""Attachments API — supporting-proof files on ledger entries.

Access model:
  * upload / delete  : plan owner OR the entry's own contributor (logged_by_user_id)
  * view / list      : anyone the plan is shared with (proof is shared evidence)

Bytes are served straight from the DB with the stored mime; images and PDFs render
inline, everything else downloads. K4: no response ever interpolates user data into HTML.
"""
from urllib.parse import quote

from flask import Blueprint, Response, g, jsonify, request

from ..models import Contact, LedgerEntry, Plan
from ..services import attachments, sharing
from ..services.attachments import AttachmentError
from .auth import current_user

bp = Blueprint("attachments", __name__, url_prefix="/api")


def _entry_for_view(user, plan_id, entry_id):
    """Plan accessible to the viewer + entry belongs to it. Returns (plan, entry, err)."""
    plan = g.db.get(Plan, plan_id)
    if plan is None:
        return None, None, (jsonify(error="not_found"), 404)
    if not sharing.accessible(g.db, plan=plan, user_id=user.id):
        return None, None, (jsonify(error="forbidden"), 403)
    entry = g.db.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        return None, None, (jsonify(error="not_found"), 404)
    return plan, entry, None


def _can_modify(user, plan, entry) -> bool:
    return user.id == plan.owner_user_id or user.id == entry.logged_by_user_id


@bp.get("/plans/<int:plan_id>/entries/<int:entry_id>/attachments")
def list_attachments(plan_id, entry_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, entry, err = _entry_for_view(user, plan_id, entry_id)
    if err:
        return err
    items = [attachments.meta(a) for a in attachments.list_for_entry(g.db, entry.id)]
    return jsonify(attachments=items), 200


@bp.post("/plans/<int:plan_id>/entries/<int:entry_id>/attachments")
def upload_attachment(plan_id, entry_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, entry, err = _entry_for_view(user, plan_id, entry_id)
    if err:
        return err
    if not _can_modify(user, plan, entry):
        return jsonify(error="forbidden",
                       detail="only the owner or this entry's contributor can attach proof"), 403
    f = request.files.get("file")
    if f is None:
        return jsonify(error="invalid", detail="no file uploaded"), 400
    raw = f.read()
    try:
        att = attachments.add_attachment(
            g.db, entry=entry, uploaded_by=user.id,
            filename=f.filename or "file", raw=raw)
        g.db.commit()
    except AttachmentError as e:
        g.db.rollback()
        # Too-large is the only one that maps to 413; the rest are plain 400s.
        code = 413 if "too large" in str(e) else 400
        return jsonify(error="invalid", detail=str(e)), code
    return jsonify(attachment=attachments.meta(att)), 201


@bp.get("/attachments/<int:att_id>")
def download_attachment(att_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    att = attachments.get(g.db, att_id)
    if att is None:
        return jsonify(error="not_found"), 404
    if att.ledger_entry_id is not None:
        # Entry attachment: any plan member may view (proof is shared evidence).
        entry = g.db.get(LedgerEntry, att.ledger_entry_id)
        plan = g.db.get(Plan, entry.plan_id) if entry else None
        if plan is None or not sharing.accessible(g.db, plan=plan, user_id=user.id):
            return jsonify(error="forbidden"), 403
    elif att.contact_id is not None:
        # Contact attachment: owner-only access (private documents).
        contact = g.db.get(Contact, att.contact_id)
        if contact is None or contact.owner_user_id != user.id:
            return jsonify(error="forbidden"), 403
    elif att.asset_plan_id is not None:
        # Asset document: any plan member may view (shared evidence).
        plan = g.db.get(Plan, att.asset_plan_id)
        if plan is None or not sharing.accessible(g.db, plan=plan, user_id=user.id):
            return jsonify(error="forbidden"), 403
    else:
        # Orphaned attachment (should not occur in practice).
        return jsonify(error="forbidden"), 403
    disp = "inline" if att.mime in attachments.INLINE_MIMES else "attachment"
    # RFC 5987 filename* — handles non-ASCII names without breaking the header.
    fn = quote(att.filename)
    return Response(att.data, mimetype=att.mime, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{fn}",
        "Content-Length": str(att.size),
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
    })


@bp.delete("/attachments/<int:att_id>")
def delete_attachment(att_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    att = attachments.get(g.db, att_id)
    if att is None:
        return jsonify(error="not_found"), 404
    if att.ledger_entry_id is not None:
        # Entry attachment: owner or uploader may delete.
        entry = g.db.get(LedgerEntry, att.ledger_entry_id)
        plan = g.db.get(Plan, entry.plan_id) if entry else None
        if plan is None:
            return jsonify(error="not_found"), 404
        if not (user.id == plan.owner_user_id or user.id == att.uploaded_by_user_id):
            return jsonify(error="forbidden",
                           detail="only the owner or the uploader can remove this attachment"), 403
    elif att.contact_id is not None:
        # Contact attachment: owner-only (same check as download).
        contact = g.db.get(Contact, att.contact_id)
        if contact is None or contact.owner_user_id != user.id:
            return jsonify(error="forbidden"), 403
    elif att.asset_plan_id is not None:
        # Asset document: owner or uploader may delete.
        plan = g.db.get(Plan, att.asset_plan_id)
        if plan is None:
            return jsonify(error="not_found"), 404
        if not (user.id == plan.owner_user_id or user.id == att.uploaded_by_user_id):
            return jsonify(error="forbidden"), 403
    else:
        return jsonify(error="not_found"), 404
    attachments.delete(g.db, att)
    g.db.commit()
    return jsonify(ok=True), 200

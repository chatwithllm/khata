from flask import Blueprint, g, jsonify, request

from ..services import contacts, attachments
from .auth import current_user

bp = Blueprint("contacts", __name__, url_prefix="/api/contacts")

_ALLOWED_FIELDS = ("name", "phone", "email", "address", "notes", "photo")


def _base_ccy(user):
    return getattr(user, "base_currency", None) or "INR"


def _meta(ct):
    return {"id": ct.id, "name": ct.name, "phone": ct.phone, "email": ct.email,
            "address": ct.address, "notes": ct.notes, "photo": ct.photo}


@bp.post("")
def create():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    d = request.get_json(silent=True) or {}
    try:
        ct = contacts.create_contact(g.db, owner_id=user.id, name=d.get("name", ""),
            phone=d.get("phone"), email=d.get("email"), address=d.get("address"),
            notes=d.get("notes"), photo=d.get("photo"))
        g.db.commit()
    except contacts.ContactError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(contact=_meta(ct)), 201


@bp.get("")
def index():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(contacts=[_meta(c) for c in contacts.list_contacts(g.db, owner_id=user.id)]), 200


@bp.get("/<int:contact_id>")
def detail(contact_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    ct = contacts.get_contact(g.db, owner_id=user.id, contact_id=contact_id)
    if ct is None:
        return jsonify(error="not_found"), 404
    rollup = contacts.contact_state(g.db, ct, base_currency=_base_ccy(user))
    return jsonify(contact=_meta(ct), rollup=rollup), 200


@bp.patch("/<int:contact_id>")
def update(contact_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    d = request.get_json(silent=True) or {}
    allowed = {k: d[k] for k in _ALLOWED_FIELDS if k in d}
    try:
        ct = contacts.update_contact(g.db, owner_id=user.id, contact_id=contact_id, **allowed)
        g.db.commit()
    except contacts.ContactError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(contact=_meta(ct)), 200


@bp.delete("/<int:contact_id>")
def remove(contact_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    try:
        contacts.delete_contact(g.db, owner_id=user.id, contact_id=contact_id)
        g.db.commit()
    except contacts.ContactError:
        g.db.rollback()
        return jsonify(error="not_found"), 404
    return "", 204


@bp.get("/<int:contact_id>/attachments")
def list_docs(contact_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    ct = contacts.get_contact(g.db, owner_id=user.id, contact_id=contact_id)
    if ct is None:
        return jsonify(error="not_found"), 404
    return jsonify(attachments=[attachments.meta(a) for a in attachments.list_for_contact(g.db, ct.id)]), 200


@bp.post("/<int:contact_id>/attachments")
def upload_doc(contact_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    ct = contacts.get_contact(g.db, owner_id=user.id, contact_id=contact_id)
    if ct is None:
        return jsonify(error="not_found"), 404
    f = request.files.get("file")
    if f is None:
        return jsonify(error="invalid", detail="no file"), 400
    try:
        a = attachments.add_attachment(g.db, contact=ct, uploaded_by=user.id,
                                       filename=f.filename, raw=f.read())
        g.db.commit()
    except attachments.AttachmentError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(attachment=attachments.meta(a)), 201

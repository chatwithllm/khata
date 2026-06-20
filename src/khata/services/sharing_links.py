"""Public share-link service for Khata plans.

Handles creation, validation, resolution, and public-state serialisation
of time-limited, token-scoped share links.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanShare


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ShareError(Exception):
    """Validation error when creating a share."""


class ShareNotFound(Exception):
    """No share with that token exists."""


class ShareGone(Exception):
    """Share exists but is expired or revoked."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SCOPES = {"summary", "full"}
_VALID_TTL_DAYS = {7, 30, 90}

# Keys dropped from the plan's state dict when scope == "summary"
_SUMMARY_DROP = {"schedule", "ledger", "deployed", "deployed_total_minor",
                 "deployed_totals", "installments",
                 "members"}  # members also in _SCRUB_KEYS (stripped from ALL scopes via _scrub)

# Keys / nested keys to scrub for PII regardless of scope
# PII / cross-plan / internal-workflow keys — stripped from the public view at all scopes
_SCRUB_KEYS = {"email", "proof_ref", "attachments", "attachment_id", "members",
               "logged_by_user_id", "plan_id", "funding_plan_id", "note",
               "display_name", "avatar", "user_id", "paid_by_name", "paid_by_avatar",
               "plan_name", "plan_type", "funding_plan_name", "funding_plan_type",
               "funding_plan_accessible", "name", "amount_status", "counter_amount_minor",
               "contributors",
               # Contact PII — defence-in-depth: strip even if loan_state ever adds contact info
               "contact", "contact_id", "contact_name", "phone", "address",
               # Asset PII — seller/buyer parties, custom fields, and external links
               "seller", "buyer", "seller_name", "buyer_name",
               "extra_fields", "links", "url"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _status(sh: PlanShare) -> str:
    """Return 'revoked', 'expired', or 'active' for a PlanShare.

    Normalises naive datetimes (SQLite returns them without tzinfo on session
    reload) before comparing to the aware UTC now.
    """
    if sh.revoked_at is not None:
        return "revoked"
    exp = sh.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return "expired" if exp <= datetime.now(timezone.utc) else "active"


def _scrub(obj: Any) -> Any:
    """Recursively remove PII keys from dicts/lists.

    State values are assumed JSON-serialisable (no tuples/sets); plain
    scalars pass through unchanged.
    """
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _SCRUB_KEYS}
    if isinstance(obj, list):
        return [_scrub(item) for item in obj]
    return obj


def _plan_state(session: Session, plan: Plan) -> dict:
    """Dispatch to the correct state serialiser based on plan.type."""
    today = date.today()

    if plan.type == "loan":
        from .loans import loan_state
        return loan_state(session, plan.loan, as_of=today)

    if plan.type == "holding":
        from .holdings import holding_state
        return holding_state(session, plan.holding)

    if plan.type == "chit":
        from .chits import chit_state
        return chit_state(session, plan.chit, as_of=today)

    if plan.type == "retirement":
        from .retirement import retirement_state
        return retirement_state(session, plan.retirement, as_of=today)

    if plan.type == "asset":
        from .assets import asset_state
        return asset_state(session, plan)

    # Unknown plan type — raise rather than silently returning empty state
    raise ShareError(f"unshareable plan type: {plan.type}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_share(
    session: Session,
    *,
    plan: Plan,
    user_id: int,
    scope: str,
    ttl_days: int,
) -> PlanShare:
    """Create and return a new PlanShare.  Does NOT flush/commit."""
    if scope not in _VALID_SCOPES:
        raise ShareError(f"Invalid scope {scope!r}; must be one of {sorted(_VALID_SCOPES)}")
    if ttl_days not in _VALID_TTL_DAYS:
        raise ShareError(
            f"Invalid ttl_days {ttl_days!r}; must be one of {sorted(_VALID_TTL_DAYS)}"
        )

    token = secrets.token_urlsafe(32)  # 43 URL-safe characters
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

    share = PlanShare(
        plan_id=plan.id,
        token=token,
        scope=scope,
        expires_at=expires_at,
        revoked_at=None,
        created_by_user_id=user_id,
    )
    session.add(share)
    return share


def list_shares(session: Session, plan: Plan) -> list[dict]:
    """Return all shares for *plan*, active and revoked, newest first."""
    rows = list(
        session.scalars(
            select(PlanShare)
            .where(PlanShare.plan_id == plan.id)
            .order_by(PlanShare.created_at.desc())
        )
    )
    result = []
    for sh in rows:
        status = _status(sh)
        result.append(
            {
                "id": sh.id,
                "token": sh.token if status == "active" else None,
                "scope": sh.scope,
                "status": status,
                "expires_at": sh.expires_at.isoformat(),
                "created_at": sh.created_at.isoformat() if sh.created_at else None,
            }
        )
    return result


def revoke_share(session: Session, *, plan: Plan, share_id: int) -> PlanShare:
    """Mark a share as revoked.

    Raises:
        ShareNotFound – share_id doesn't exist or belongs to a different plan.

    Idempotent: calling on an already-revoked share is a no-op (the original
    ``revoked_at`` timestamp is preserved).
    """
    share = session.scalar(
        select(PlanShare).where(PlanShare.id == share_id, PlanShare.plan_id == plan.id)
    )
    if share is None:
        raise ShareNotFound(share_id)
    if share.revoked_at is None:
        share.revoked_at = datetime.now(timezone.utc)
    return share


def resolve_public(session: Session, token: str) -> tuple[Plan, str]:
    """Look up a token and return *(plan, scope)*.

    Raises:
        ShareNotFound – token doesn't exist at all.
        ShareGone     – token exists but is expired or revoked.
    """
    share = session.scalar(select(PlanShare).where(PlanShare.token == token))
    if share is None:
        raise ShareNotFound(token)

    if _status(share) != "active":
        raise ShareGone(token)

    plan = session.get(Plan, share.plan_id)
    return plan, share.scope


def public_state(session: Session, plan: Plan, scope: str) -> dict:
    """Return a sanitised, scope-limited state envelope for public rendering.

    The envelope always contains:
        plan_type, name, currency, status, scope, owner_name, as_of

    Plus a ``state`` dict with keys determined by *scope*:
        - "full"    → all keys, PII scrubbed
        - "summary" → drop detailed keys (schedule, ledger, deployed, …)
    """
    from ..models import User

    raw_state = _plan_state(session, plan)

    if scope == "summary":
        raw_state = {k: v for k, v in raw_state.items() if k not in _SUMMARY_DROP}

    scrubbed_state = _scrub(raw_state)

    owner = session.get(User, plan.owner_user_id)
    owner_name = owner.display_name if owner is not None else None

    return {
        "plan_type": plan.type,
        "name": plan.name,
        "currency": plan.currency,
        "status": plan.status,
        "scope": scope,
        "owner_name": owner_name,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "state": scrubbed_state,
    }

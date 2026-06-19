"""Public share-link service for Khata plans.

Handles creation, validation, resolution, and public-state serialisation
of time-limited, token-scoped share links.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
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
_SUMMARY_DROP = {"schedule", "ledger", "deployed", "deployed_total_minor", "deployed_totals"}

# Keys / nested keys to scrub for PII regardless of scope
_SCRUB_KEYS = {"email", "proof_ref", "attachments", "attachment_id", "members"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scrub(obj: Any) -> Any:
    """Recursively remove PII keys from dicts/lists."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _SCRUB_KEYS}
    if isinstance(obj, list):
        return [_scrub(item) for item in obj]
    return obj


def _plan_state(session: Session, plan: Plan) -> dict:
    """Dispatch to the correct state serialiser based on plan.type."""
    from datetime import date as _date

    today = _date.today()

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

    # Unknown plan type — return minimal info
    return {}


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
    now = datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(PlanShare)
            .where(PlanShare.plan_id == plan.id)
            .order_by(PlanShare.created_at.desc())
        )
    )
    result = []
    for sh in rows:
        if sh.revoked_at is not None:
            status = "revoked"
        elif sh.expires_at <= now:
            status = "expired"
        else:
            status = "active"
        result.append(
            {
                "id": sh.id,
                "token": sh.token,
                "scope": sh.scope,
                "status": status,
                "expires_at": sh.expires_at.isoformat(),
                "created_at": sh.created_at.isoformat() if sh.created_at else None,
            }
        )
    return result


def revoke_share(session: Session, *, plan: Plan, share_id: int) -> PlanShare:
    """Mark a share as revoked. Raises ShareNotFound if it doesn't belong to plan."""
    share = session.scalar(
        select(PlanShare).where(PlanShare.id == share_id, PlanShare.plan_id == plan.id)
    )
    if share is None:
        raise ShareNotFound(share_id)
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

    now = datetime.now(timezone.utc)
    if share.revoked_at is not None or share.expires_at <= now:
        raise ShareGone(token)

    plan = session.get(Plan, share.plan_id)
    return plan, share.scope


def public_state(session: Session, plan: Plan, scope: str) -> dict:
    """Return a sanitised, scope-limited state envelope for public rendering.

    The envelope always contains:
        plan_type, name, currency, scope

    Plus a ``state`` dict with keys determined by *scope*:
        - "full"    → all keys, PII scrubbed
        - "summary" → drop detailed keys (schedule, ledger, deployed, …)
    """
    raw_state = _plan_state(session, plan)

    if scope == "summary":
        raw_state = {k: v for k, v in raw_state.items() if k not in _SUMMARY_DROP}

    scrubbed_state = _scrub(raw_state)

    return {
        "plan_type": plan.type,
        "name": plan.name,
        "currency": plan.currency,
        "scope": scope,
        "state": scrubbed_state,
    }

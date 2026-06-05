# Khata Phase 5 · Plan 5.4 — Live Market Feeds (optional) Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** An **optional** live-price feed seam — refresh a holding's quote from a configured market-data
provider — with **graceful degradation to manual entry** when no feed is configured. Spec inline (small).

**Design (recommended, locked — mirrors the Google-sign-in pattern):**
- A config flag `KHATA_PRICE_FEED` (a provider key/URL). **Unset ⇒ feeds off ⇒ manual quotes only** (the
  whole app already works that way). Set ⇒ feeds enabled.
- An **injectable price provider** `app.config["PRICE_PROVIDER"]` (default `live_price_provider`, which
  out-of-the-box raises `FeedError("no price provider configured")` — self-hosters wire their own data
  source, exactly like supplying a Google client ID). Tests override it with a stub.
- `GET /api/feed/config` → `{enabled}` so the UI shows the "Refresh (live)" button only when configured.
- `POST /api/plans/<id>/holding/refresh-quote` (owner-only) → if disabled `503 feed_not_configured`; else
  call the provider for `(asset_class, symbol, currency)`, `set_quote` with the spot, return `{state}`.
- No new model/migration. Manual quote (`POST /holding/quote`) is unchanged and always available.

---

### Task 1: Feed config + provider seam + refresh-quote API

**Files:** Modify `src/khata/config.py`, `src/khata/__init__.py`, `src/khata/api/plans.py`; Create `src/khata/services/feed.py`, `src/khata/api/feed.py`; Test `tests/test_feed_api.py`

- [ ] **Step 1: Write `tests/test_feed_api.py`**
```python
import pytest
from khata import create_app
from khata.config import Config
from khata.db import Base


def _app(feed=None, provider=None):
    cfg = Config(); cfg.database_url = "sqlite:///:memory:"; cfg.price_feed = feed
    app = create_app(cfg); app.config["TESTING"] = True
    if provider is not None:
        app.config["PRICE_PROVIDER"] = provider
    Base.metadata.create_all(app.config["ENGINE"])
    return app


def _reg(c): return c.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})


def _mk_holding(c):
    return c.post("/api/plans", json={"type": "holding", "name": "Gold", "currency": "INR",
                  "asset_class": "gold", "unit": "gram"}).get_json()["plan"]["id"]


def test_feed_config_disabled_by_default():
    c = _app().test_client(); _reg(c)
    assert c.get("/api/feed/config").get_json()["enabled"] is False


def test_feed_config_enabled_when_set():
    c = _app(feed="demo").test_client(); _reg(c)
    assert c.get("/api/feed/config").get_json()["enabled"] is True


def test_refresh_quote_disabled_503():
    c = _app().test_client(); _reg(c); pid = _mk_holding(c)
    assert c.post(f"/api/plans/{pid}/holding/refresh-quote").status_code == 503


def test_refresh_quote_uses_provider():
    # provider returns ₹61,000/g = 6100000 minor for any holding
    c = _app(feed="demo", provider=lambda asset_class, symbol, currency, feed_cfg: 6100000).test_client()
    _reg(c); pid = _mk_holding(c)
    r = c.post(f"/api/plans/{pid}/holding/refresh-quote")
    assert r.status_code == 200
    assert r.get_json()["state"]["current_price_minor"] == 6100000


def test_refresh_quote_requires_auth_and_owner():
    c = _app(feed="demo").test_client()
    assert c.post("/api/plans/1/holding/refresh-quote").status_code == 401
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: `src/khata/config.py`** — in `Config.__init__`, after `google_client_id`:
```python
        self.price_feed = os.environ.get("KHATA_PRICE_FEED")
```

- [ ] **Step 4: Create `src/khata/services/feed.py`**
```python
class FeedError(Exception):
    pass


def feed_enabled(cfg) -> bool:
    return bool(getattr(cfg, "price_feed", None))


def live_price_provider(asset_class, symbol, currency, feed_config):
    """Default provider — NOT wired out of the box. A self-hoster sets KHATA_PRICE_FEED and either
    overrides app.config['PRICE_PROVIDER'] or implements a fetch here (lazily importing `requests`)
    against their market-data source, returning an integer price in minor units per whole unit.
    Until then, feeds raise and the app stays on manual quotes."""
    raise FeedError("no price provider configured")
```

- [ ] **Step 5: Create `src/khata/api/feed.py`**
```python
from flask import Blueprint, current_app, jsonify

from ..services import feed
from .auth import current_user

bp = Blueprint("feed", __name__)


@bp.get("/api/feed/config")
def feed_config():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(enabled=feed.feed_enabled(current_app.config["KHATA"])), 200
```

- [ ] **Step 6: Register feed blueprint + default provider in `src/khata/__init__.py`** — after the
  `GOOGLE_VERIFIER` line add:
```python
    from .services.feed import live_price_provider
    app.config["PRICE_PROVIDER"] = live_price_provider
```
  And after the networth/analysis blueprint registrations add:
```python
    from .api.feed import bp as feed_bp
    app.register_blueprint(feed_bp)
```

- [ ] **Step 7: Add the refresh-quote endpoint to `src/khata/api/plans.py`** (import `feed` from
  `..services` and `current_app`/`datetime`,`timezone` as needed — check existing imports first):
```python
@bp.post("/<int:plan_id>/holding/refresh-quote")
def holding_refresh_quote(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    cfg = current_app.config["KHATA"]
    if not feed.feed_enabled(cfg):
        return jsonify(error="feed_not_configured"), 503
    provider = current_app.config["PRICE_PROVIDER"]
    try:
        price = provider(plan.holding.asset_class, plan.holding.symbol, plan.currency, cfg.price_feed)
        holdings.set_quote(g.db, plan=plan, price_minor=price, as_of=_parse_dt(None))
        g.db.commit()
    except (feed.FeedError, HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="feed_error", detail=str(e)), 502
    return jsonify(state=holdings.holding_state(g.db, plan.holding)), 200
```
(`_parse_dt(None)` returns "now"; confirm that — `_parse_dt` defaults to `datetime.now(timezone.utc)` when
the arg is falsy. Add `from flask import current_app` to the imports if not present; `feed` to the
`from ..services import …` line.)

- [ ] **Step 8: Run + full suite** — `pytest tests/test_feed_api.py -q` (5), then `pytest -q` (expect 177 — 172 + 5).

- [ ] **Step 9: Commit** `feat(feed): optional live-price seam — /api/feed/config + holding refresh-quote (manual fallback)`.

---

### Task 2: Holding-detail "Refresh (live)" button + docs

**Files:** Modify `src/khata/static/holding-detail.html`; Test `tests/test_web.py`; docs.

- [ ] In `holding-detail.html`: on load, `fetch('/api/feed/config')`; if `enabled`, reveal a **Refresh
  price (live)** button (next to the existing Buy/Sell/Quote action) that `POST`s
  `/api/plans/<pid>/holding/refresh-quote` and reloads on success (error via textContent — e.g. the
  502/503 detail). If not enabled, the button stays hidden (manual quote is unaffected). All createElement
  (K4). Add a `tests/test_web.py` assertion that `/holding/1` body references `/holding/refresh-quote` and
  `/api/feed/config`. Done-gate: with a stubbed provider + feed enabled, refresh sets the quote; with feed
  off, `/api/feed/config` enabled=false. Commit `feat(web): holding live-price refresh button (when feed configured)`.
- [ ] Append `docs/AGENT_LEARNINGS.md` (Plan 5.4: optional feed seam — config flag + injectable
  `PRICE_PROVIDER`, graceful degradation to manual quotes when unset, like Google sign-in; refresh-quote
  503 when off; the default provider is unwired so self-hosters supply their own). Flip 5.4 box + mark
  **Phase 5 + the ROADMAP complete** in Progress.md + ROADMAP.md; tests 177. Commit (orchestrator owns build_status.json).

---

## Self-Review
Feed seam mirrors Google sign-in: `KHATA_PRICE_FEED` flag + injectable `PRICE_PROVIDER` + `/api/feed/config`
+ owner-only `refresh-quote` (503 when off, 502 on provider error). Default unwired ⇒ manual quotes (no
behavior change out of the box). Tested via a stub provider. No model/migration. Tests 172→177. ✓

## Done
This is the final plan — Phase 5 and the entire roadmap complete after this.

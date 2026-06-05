# Khata Phase 5 · Plan 5.3 — Analysis Tools Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. **Pure calculator (money) → review Task 1.** Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** A stateless **hold-vs-sell** decision calculator (e.g. gold loan vs selling the gold): compare keeping an appreciating asset + borrowing-against-it (paying interest) vs selling it. Pure derived math + an `/analysis` page. Spec is inline here (small, single calculator).

**Design (recommended, locked):** Given an asset's current value + assumed appreciation, a borrow amount + loan interest rate, and a horizon, compute: the asset's future value, the appreciation gain (hold), the interest cost of borrowing (hold), and the **net advantage of holding** = appreciation_gain − interest_cost. Verdict "hold" if net > 0 else "sell". Compound monthly appreciation (`Decimal ** int`); **simple** interest on the borrowed principal over the horizon (a gold loan held bullet-style). No storage. All Decimal, no float.

---

### Task 1: Analysis service + API  ⟶ REVIEW (money calc)

**Files:** Create `src/khata/services/analysis.py`; Modify `src/khata/api/` (new blueprint) + `src/khata/__init__.py`; Test `tests/test_analysis_service.py`, `tests/test_analysis_api.py`

- [ ] **Step 1: Write `tests/test_analysis_service.py`** (exact constants pre-computed with Decimal):
```python
import pytest
from khata.services.analysis import hold_vs_sell, AnalysisError


def test_hold_wins():
    # gold ₹10,00,000, appreciation 10%/yr, borrow ₹6,00,000 at 9%/yr, 18 months
    d = hold_vs_sell(asset_value_minor=100000000, appreciation_bps=1000,
                     borrow_amount_minor=60000000, interest_bps=900, horizon_months=18)
    assert d["future_value_minor"] == 116111233
    assert d["appreciation_gain_minor"] == 16111233
    assert d["interest_cost_minor"] == 8100000          # 6L × 9% × 1.5yr
    assert d["net_hold_advantage_minor"] == 8011233
    assert d["verdict"] == "hold"


def test_sell_wins_when_no_appreciation():
    d = hold_vs_sell(asset_value_minor=100000000, appreciation_bps=0,
                     borrow_amount_minor=60000000, interest_bps=900, horizon_months=12)
    assert d["appreciation_gain_minor"] == 0
    assert d["interest_cost_minor"] == 5400000           # 6L × 9% × 1yr
    assert d["net_hold_advantage_minor"] == -5400000
    assert d["verdict"] == "sell"


def test_validation():
    with pytest.raises(AnalysisError):
        hold_vs_sell(asset_value_minor=0, appreciation_bps=1000, borrow_amount_minor=1,
                     interest_bps=900, horizon_months=12)        # asset_value <= 0
    with pytest.raises(AnalysisError):
        hold_vs_sell(asset_value_minor=100000000, appreciation_bps=1000, borrow_amount_minor=1,
                     interest_bps=900, horizon_months=0)         # horizon <= 0
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Create `src/khata/services/analysis.py`**
```python
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session  # noqa: F401  (kept for signature symmetry / future use)


class AnalysisError(Exception):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def hold_vs_sell(*, asset_value_minor: int, appreciation_bps: int, borrow_amount_minor: int,
                 interest_bps: int, horizon_months: int) -> dict:
    """Hold-an-appreciating-asset-and-borrow vs sell-it. Pure; derived; no float."""
    if asset_value_minor <= 0:
        raise AnalysisError("asset value must be > 0")
    if horizon_months <= 0:
        raise AnalysisError("horizon must be > 0 months")
    if appreciation_bps < 0 or interest_bps < 0 or borrow_amount_minor < 0:
        raise AnalysisError("rates and amounts must be >= 0")
    monthly_appr = Decimal(appreciation_bps) / 120000
    future = _round(Decimal(asset_value_minor) * ((Decimal(1) + monthly_appr) ** horizon_months))
    appreciation_gain = future - asset_value_minor
    # simple interest on the borrowed principal over the horizon (bullet gold-loan style)
    interest_cost = _round(Decimal(borrow_amount_minor) * Decimal(interest_bps) / 10000
                           * Decimal(horizon_months) / 12)
    net = appreciation_gain - interest_cost
    return {
        "asset_value_minor": asset_value_minor, "borrow_amount_minor": borrow_amount_minor,
        "horizon_months": horizon_months, "future_value_minor": future,
        "appreciation_gain_minor": appreciation_gain, "interest_cost_minor": interest_cost,
        "net_hold_advantage_minor": net, "verdict": "hold" if net > 0 else "sell",
    }
```

- [ ] **Step 4: Write `tests/test_analysis_api.py`** (mirror holdings-api fixture):
```python
import pytest
from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config(); cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg); app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _reg(c): return c.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})


def test_analysis_requires_auth(client):
    assert client.get("/api/analysis/hold-vs-sell").status_code == 401


def test_analysis_hold_vs_sell(client):
    _reg(client)
    r = client.get("/api/analysis/hold-vs-sell",
                   query_string={"asset_value": "10,00,000", "appreciation": "10",
                                 "borrow": "6,00,000", "interest": "9", "horizon": "18"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["net_hold_advantage_minor"] == 8011233 and d["verdict"] == "hold"


def test_analysis_bad_input_400(client):
    _reg(client)
    assert client.get("/api/analysis/hold-vs-sell",
                      query_string={"asset_value": "abc", "appreciation": "10", "borrow": "6,00,000",
                                    "interest": "9", "horizon": "18"}).status_code == 400
```

- [ ] **Step 5: Create `src/khata/api/analysis.py`**
```python
from flask import Blueprint, jsonify, request

from ..money import pct_to_bps, to_minor
from ..services import analysis
from .auth import current_user

bp = Blueprint("analysis", __name__)


@bp.get("/api/analysis/hold-vs-sell")
def hold_vs_sell():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    a = request.args
    try:
        result = analysis.hold_vs_sell(
            asset_value_minor=to_minor(a.get("asset_value", ""), "INR"),
            appreciation_bps=pct_to_bps(a.get("appreciation", "0")),
            borrow_amount_minor=to_minor(a.get("borrow", "0"), "INR"),
            interest_bps=pct_to_bps(a.get("interest", "0")),
            horizon_months=int(a.get("horizon", "0")))
    except (analysis.AnalysisError, ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(result), 200
```

- [ ] **Step 6: Register in `src/khata/__init__.py`** — after the networth blueprint registration:
```python
    from .api.analysis import bp as analysis_bp
    app.register_blueprint(analysis_bp)
```

- [ ] **Step 7: Run + full suite** — `pytest tests/test_analysis_service.py tests/test_analysis_api.py -q`, then `pytest -q` (expect 171 — 165 + 6).

- [ ] **Step 8: Commit** `feat(analysis): hold-vs-sell decision calculator + GET /api/analysis/hold-vs-sell`.

---

### Task 2: Analysis page + route + nav + docs

**Files:** Create `src/khata/static/analysis.html`; Modify `src/khata/web.py`, `src/khata/static/app.html`; Test `tests/test_web.py`; docs.

- [ ] `/analysis` route → `analysis.html`. Page (on ledger.css, auth-guard 401→/): inputs — asset value,
  appreciation %, borrow amount, loan interest %, horizon (months) — + a **Calculate** button →
  `GET /api/analysis/hold-vs-sell?...` → render a result panel: future value, appreciation gain, interest
  cost, **net advantage** (green if hold / red if sell), and a verdict line ("Holding wins by ₹X" /
  "Selling wins by ₹X — the interest outweighs the appreciation"). Errors via textContent. All
  createElement (K4). Add an **Analysis** link to `app.html` sidebar (in the "More" section, like
  Settings). Test `test_web.py`: `/analysis` 200 + `/api/analysis/hold-vs-sell`, `ledger.css`. Done-gate:
  hit the real endpoint via the page's query, verify net 8011233 / verdict hold. Commit
  `feat(web): hold-vs-sell analysis page`.
- [ ] Append `docs/AGENT_LEARNINGS.md` (Plan 5.3: pure stateless hold-vs-sell calculator — compound
  appreciation `Decimal**int`, simple interest on borrow; verdict net>0→hold; new `analysis` blueprint;
  `/analysis` page). Flip 5.3 boxes in Progress.md + ROADMAP.md; tests 171. Commit (orchestrator owns build_status.json).

---

## Self-Review
hold_vs_sell pure/derived: compound appreciation (Decimal**int), simple interest on borrow, net =
gain − interest, verdict by sign. Constants pre-computed (116111233 / 8011233 / hold; −5400000 / sell).
Auth-gated GET; bad input → 400 (to_minor now raises ValueError per 5.2). Tests 165→171. Money review on
Task 1. ✓

## Next
5.4 Live market feeds (optional).

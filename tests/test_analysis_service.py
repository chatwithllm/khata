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

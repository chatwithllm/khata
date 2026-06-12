from datetime import datetime

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services import fx


@pytest.fixture
def s():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as sess:
        yield sess


def test_claim_once_per_day(s):
    now = datetime(2026, 6, 11, 9, 0)
    assert fx.claim_daily_refresh(s, now=now) is True       # first caller wins
    assert fx.claim_daily_refresh(s, now=now) is False      # same day → already claimed
    nxt = datetime(2026, 6, 12, 0, 5)
    assert fx.claim_daily_refresh(s, now=nxt) is True       # new day → claimable again


def test_release_claim_allows_retry(s):
    now = datetime(2026, 6, 11, 9, 0)
    prev = fx.refresh_last_run(s)                            # None on a fresh DB
    assert fx.claim_daily_refresh(s, now=now) is True
    fx.release_refresh_claim(s, previous=prev)               # fetch failed → give back
    assert fx.claim_daily_refresh(s, now=now) is True        # retry same day succeeds


def test_fx_tick_stores_canonical_inr_per_usd(s, monkeypatch):
    """_fx_tick end-to-end: claim → fetch_latest(USD,INR) → set_rate(INR,USD)."""
    import khata.scheduler as sched

    class _App:
        config = {}
    # fake session factory returning OUR session (context-manager protocol)
    class _SF:
        def __call__(self):
            return self
        def __enter__(self):
            return s
        def __exit__(self, *a):
            return False
    _App.config["SESSION_FACTORY"] = _SF()
    monkeypatch.setattr(sched, "fx_live", type("L", (), {
        "fetch_latest": staticmethod(lambda base, quote: 88_120_000)}))
    sched._fx_tick(_App())
    assert fx.get_rate(s, "INR", "USD") == 88_120_000        # canonical direction


def test_fx_tick_failure_keeps_old_rate_and_releases_claim(s, monkeypatch):
    import khata.scheduler as sched
    from datetime import datetime as dt, timezone
    fx.set_rate(s, base="INR", quote="USD", rate_micro=80_000_000,
                as_of=dt(2026, 6, 10, tzinfo=timezone.utc))
    s.commit()

    class _App:
        config = {}
    class _SF:
        def __call__(self):
            return self
        def __enter__(self):
            return s
        def __exit__(self, *a):
            return False
    _App.config["SESSION_FACTORY"] = _SF()
    monkeypatch.setattr(sched, "fx_live", type("L", (), {
        "fetch_latest": staticmethod(lambda base, quote: None)}))
    sched._fx_tick(_App())
    assert fx.get_rate(s, "INR", "USD") == 80_000_000        # old rate kept
    assert fx.claim_daily_refresh(s, now=datetime(2026, 6, 11, 10, 0)) is True  # retryable

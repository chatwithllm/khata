"""In-app automatic-backup scheduler.

A BackgroundScheduler ticks hourly. Each tick atomically claims the backup slot via the
DB (`backup_store.claim_due`), so even with multiple gunicorn workers each running their
own scheduler, exactly one performs a given period's backup. Started from create_app only
when KHATA_ENABLE_SCHEDULER=1 (kept off in tests so no threads spawn).
"""
from datetime import datetime, timedelta, timezone

from .services import backup_store, fx, fx_live


def _tick(app) -> None:
    SessionLocal = app.config["SESSION_FACTORY"]
    db_url = app.config["KHATA"].database_url
    now = datetime.now()                    # naive server-local (matches config.hour)
    with SessionLocal() as s:
        try:
            if not backup_store.claim_due(s, now=now):
                return                       # not due, or another worker claimed it
            cfg = backup_store.get_config(s)
            stamp = now.strftime("%Y%m%d-%H%M%S")
            res = backup_store.run_backup(s, database_url=db_url,
                                          retention=cfg.retention, stamp=stamp)
            cfg.last_status = f"ok · {res['filename']} ({res['size']} bytes, pruned {res['pruned']})"
            s.commit()
        except Exception as e:               # never let a backup error kill the scheduler thread
            s.rollback()
            try:
                cfg = backup_store.get_config(s)
                cfg.last_status = f"error · {e}"
                s.commit()
            except Exception:
                pass


def _fx_tick(app) -> None:
    """Once per UTC day (hourly checks, atomic claim): refresh the canonical
    INR/USD rate from frankfurter. fetch_latest("USD","INR") returns INR-per-USD
    (frankfurter is quote-per-base); the canonical FxRate row is base=INR,
    quote=USD (base-per-quote) — same number, stored Settings-compatible.
    Fetch failure → release the claim (retry next hour) and keep the old rate."""
    SessionLocal = app.config["SESSION_FACTORY"]
    now = datetime.now()
    with SessionLocal() as s:
        try:
            prev = fx.refresh_last_run(s)
            if not fx.claim_daily_refresh(s, now=now):
                return
            rate = fx_live.fetch_latest("USD", "INR")
            if rate:
                fx.set_rate(s, base="INR", quote="USD", rate_micro=rate,
                            as_of=datetime.now(timezone.utc))
                s.commit()
            else:
                fx.release_refresh_claim(s, previous=prev)
        except Exception:        # never let an FX error kill the scheduler thread
            s.rollback()


def start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler(daemon=True)
    # first check shortly after boot (catch a missed window), then hourly
    sched.add_job(lambda: _tick(app), "interval", minutes=60, id="auto-backup",
                  next_run_time=datetime.now() + timedelta(seconds=45),
                  max_instances=1, coalesce=True)
    sched.add_job(lambda: _fx_tick(app), "interval", minutes=60, id="fx-refresh",
                  next_run_time=datetime.now() + timedelta(seconds=75),
                  max_instances=1, coalesce=True)
    sched.start()
    app.config["SCHEDULER"] = sched
    return sched

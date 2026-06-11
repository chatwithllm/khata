"""In-app automatic-backup scheduler.

A BackgroundScheduler ticks hourly. Each tick atomically claims the backup slot via the
DB (`backup_store.claim_due`), so even with multiple gunicorn workers each running their
own scheduler, exactly one performs a given period's backup. Started from create_app only
when KHATA_ENABLE_SCHEDULER=1 (kept off in tests so no threads spawn).
"""
from datetime import datetime, timedelta

from .services import backup_store


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


def start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler(daemon=True)
    # first check shortly after boot (catch a missed window), then hourly
    sched.add_job(lambda: _tick(app), "interval", minutes=60, id="auto-backup",
                  next_run_time=datetime.now() + timedelta(seconds=45),
                  max_instances=1, coalesce=True)
    sched.start()
    app.config["SCHEDULER"] = sched
    return sched

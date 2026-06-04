from flask import Flask, g, jsonify

from .config import Config
from .db import make_engine, make_session_factory


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    cfg = config or Config()
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg

    engine = make_engine(cfg.database_url)
    SessionLocal = make_session_factory(engine)
    app.config["ENGINE"] = engine
    app.config["SESSION_FACTORY"] = SessionLocal

    @app.before_request
    def _open_session():
        g.db = SessionLocal()

    @app.teardown_request
    def _close_session(exc):
        db = g.pop("db", None)
        if db is not None:
            if exc is not None:
                db.rollback()
            db.close()

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    from .api.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .web import bp as web_bp
    app.register_blueprint(web_bp)

    from .api.plans import bp as plans_bp
    app.register_blueprint(plans_bp)

    return app

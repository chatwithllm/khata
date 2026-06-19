import os

from flask import Flask, g, jsonify, request

from .config import Config
from .db import make_engine, make_session_factory


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    cfg = config or Config()
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg
    # Hard ceiling on request bodies: attachment files cap at 25 MB (services/attachments);
    # allow headroom for multipart overhead. Bigger bodies are rejected at the WSGI layer.
    app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

    # When served behind a trusted HTTPS reverse proxy, trust its forwarded headers so
    # request.scheme is "https", and mark the session cookie Secure. Opt-in via
    # KHATA_SECURE_COOKIES so direct-http testing on :5057 keeps working (a Secure
    # cookie is never sent over http -> would silently break login).
    if cfg.secure_cookies:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
        )

    from .services.auth import verify_google_credential
    app.config["GOOGLE_VERIFIER"] = verify_google_credential

    from .services.feed import live_price_provider
    app.config["PRICE_PROVIDER"] = live_price_provider

    engine = make_engine(cfg.database_url)
    SessionLocal = make_session_factory(engine)
    app.config["ENGINE"] = engine
    app.config["SESSION_FACTORY"] = SessionLocal

    # The mobile client calls the JSON API cross-origin (it isn't served from this
    # host). Native iOS/Android don't enforce CORS, but Expo web and the dev tools
    # do, so allow the API surface to be called from any origin with a bearer token.
    # Auth is by Authorization header, never by cross-origin cookie, so we do NOT
    # set Allow-Credentials and a wildcard origin is safe.
    @app.after_request
    def _api_cors(resp):
        if request.path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    @app.before_request
    def _cors_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return ("", 204)

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

    from .api.invitations import bp as invitations_bp
    app.register_blueprint(invitations_bp)

    from .api.confirmations import bp as confirmations_bp
    app.register_blueprint(confirmations_bp)

    from .api.backup import bp as backup_bp
    app.register_blueprint(backup_bp)

    from .api.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from .api.networth import bp as networth_bp
    app.register_blueprint(networth_bp)

    from .api.analysis import bp as analysis_bp
    app.register_blueprint(analysis_bp)

    from .api.feed import bp as feed_bp
    app.register_blueprint(feed_bp)

    from .api.attachments import bp as attachments_bp
    app.register_blueprint(attachments_bp)

    from .api.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    from .api.public import bp as public_bp
    app.register_blueprint(public_bp)

    # Automatic-backup scheduler — opt-in via env so tests never spawn threads. Enabled
    # by run-app.sh (dev) and the prod .env.prod.
    if os.environ.get("KHATA_ENABLE_SCHEDULER") == "1":
        from .scheduler import start_scheduler
        start_scheduler(app)

    return app

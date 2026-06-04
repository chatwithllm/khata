from flask import Flask, jsonify

from .config import Config


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    cfg = config or Config()
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    return app

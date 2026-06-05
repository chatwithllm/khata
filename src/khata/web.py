from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("web", __name__)


def _static_dir() -> str:
    return current_app.static_folder


@bp.get("/")
def landing():
    return send_from_directory(_static_dir(), "index.html")


@bp.get("/app")
def app_shell():
    return send_from_directory(_static_dir(), "app.html")


@bp.get("/features")
def features():
    return send_from_directory(_static_dir(), "features.html")


@bp.get("/holdings")
def holdings():
    return send_from_directory(_static_dir(), "holdings.html")


@bp.get("/create")
def create_plan():
    return send_from_directory(_static_dir(), "create-plan.html")


@bp.get("/asset/<int:plan_id>")
def asset_detail(plan_id):
    return send_from_directory(_static_dir(), "asset-detail.html")

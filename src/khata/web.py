from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("web", __name__)


@bp.after_request
def _no_store_html(resp):
    # HTML pages carry evolving inline JS; never let a browser serve a stale page.
    # Versioned static assets (ledger.css?v=N, app.css) stay cacheable.
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


def _static_dir() -> str:
    return current_app.static_folder


@bp.get("/")
def landing():
    return send_from_directory(_static_dir(), "index.html")


@bp.get("/welcome")
def welcome():
    # Marketing/landing site — standalone static page, shared by link.
    return send_from_directory(_static_dir(), "welcome.html")


@bp.get("/join")
def join():
    # Invite-link landing — reads ?token, lets the invited user set up their account.
    return send_from_directory(_static_dir(), "join.html")


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


@bp.get("/loan/<int:plan_id>")
def loan_detail(plan_id):
    return send_from_directory(_static_dir(), "loan-detail.html")


@bp.get("/holding/<int:plan_id>")
def holding_detail(plan_id):
    return send_from_directory(_static_dir(), "holding-detail.html")


@bp.get("/chit/<int:plan_id>")
def chit_detail(plan_id):
    return send_from_directory(_static_dir(), "chit-detail.html")


@bp.get("/retirement/<int:plan_id>")
def retirement_detail(plan_id):
    return send_from_directory(_static_dir(), "retirement-detail.html")


@bp.get("/settings")
def settings():
    return send_from_directory(_static_dir(), "settings.html")


@bp.get("/analysis")
def analysis():
    return send_from_directory(_static_dir(), "analysis.html")

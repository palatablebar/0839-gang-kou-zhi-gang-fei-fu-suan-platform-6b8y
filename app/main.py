import os
from pathlib import Path

from flask import Flask, jsonify, render_template
from werkzeug.exceptions import RequestEntityTooLarge

from app.accrual.routes import accrual_api
from app.accrual.store import AccrualStore
from app.catalog import SPEC
from app.config import MAX_FILE, ROOT
from app.errors import DomainIssue, error_response
from app.review.store import Store
from app.routes import api


def create_app(database=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE + 64 * 1024
    app.extensions["runs"] = Store(database or os.getenv("WORKBENCH_DB", str(ROOT / "instance" / "workbench.sqlite3")))
    accrual_db = os.getenv("ACCRUAL_DB") or str(
        Path(app.extensions["runs"].path).parent / "accrual.sqlite3")
    app.extensions["accruals"] = AccrualStore(accrual_db)
    app.register_error_handler(DomainIssue, error_response)
    app.register_error_handler(RequestEntityTooLarge, lambda _: error_response(DomainIssue("FILE_TOO_LARGE", 413)))
    app.register_blueprint(api)
    app.register_blueprint(accrual_api)

    @app.get("/")
    def home():
        return render_template("index.html", p=SPEC)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    return app


app = create_app()

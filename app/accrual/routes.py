from flask import Blueprint, jsonify, request

from app.accrual import service

accrual_api = Blueprint("accrual_api", __name__)


def store():
    from flask import current_app
    return current_app.extensions["accruals"]


def body():
    return request.get_json(silent=True) or {}


@accrual_api.post("/api/accruals/entries")
def post_accrual():
    return jsonify(service.post_accrual(store(), body()))


@accrual_api.post("/api/accruals/settlements")
def post_settlement():
    return jsonify(service.post_settlement(store(), body()))


@accrual_api.post("/api/accruals/periods/<period>/close")
def close_period(period):
    return jsonify(service.close_period(store(), period))


@accrual_api.get("/api/accruals/periods")
def list_periods():
    return jsonify(store().list_periods())


@accrual_api.get("/api/accruals/entries")
def list_entries():
    data = request.args
    return jsonify(store().list_entries(
        container_id=data.get("container_id"), period=data.get("period")))


@accrual_api.post("/api/accruals/reconcile")
def reconcile():
    return jsonify(service.reconcile(store(), body()))

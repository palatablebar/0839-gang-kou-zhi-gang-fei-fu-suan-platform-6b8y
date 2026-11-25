import hashlib

from app.accrual import domain
from app.errors import DomainIssue


def _request_key(prefix, **parts):
    """由业务要素派生确定性请求键：同一请求重试得到同一键，天然不重复入账。"""
    raw = "|".join([prefix] + [str(parts[key]) for key in sorted(parts)])
    return prefix + "_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _parse_trip(data):
    required = ("container_id", "gate_in", "free_days")
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        raise DomainIssue("BAD_REQUEST", detail="缺少字段: " + ",".join(missing))
    return dict(data)


def _validate_period(period):
    try:
        domain.validate_period(period or "")
    except ValueError:
        raise DomainIssue("BAD_REQUEST", detail="历月格式应为 YYYY-MM")


def post_accrual(store, data):
    """月底暂估入账：截至 period 月末已产生的滞港费，差额（可含 0）入账。

    幂等优先：请求键（显式传入或由业务要素派生）命中时直接返回原分录，
    保证关账/入账失败后的重试不会重复入账。
    """
    trip = _parse_trip(data)
    period = data.get("period")
    _validate_period(period)
    already = store.booked_cents(trip["container_id"], before_period=period)
    request_key = data.get("idempotency_key") or _request_key(
        "ACCRUAL", c=trip["container_id"], p=period, g=trip["gate_in"], f=trip["free_days"], b=already)
    existing = store.find_by_request(request_key)
    if existing is not None:
        existing["created"] = False
        return existing
    # 新写请求先查历月关账状态：关账后旧账不能改
    if store.period_status(period)["status"] == "CLOSED":
        raise DomainIssue("PERIOD_CLOSED", 409)
    # 再检查业务约束：同一历月不能重复暂估
    if any(item["period"] == period and item["entry_type"] == domain.ACCRUAL
           for item in store.list_entries(container_id=trip["container_id"], period=period)):
        raise DomainIssue("ENTRY_EXISTS", 409)
    try:
        entry = domain.build_accrual_entry(trip, period, already)
    except ValueError as exc:
        raise DomainIssue(str(exc), 400)
    row, created = store.post_entry(entry, request_key)
    row["created"] = created
    return row


def post_settlement(store, data):
    """出港实结：整趟实费与历月已入账合计的差额计入本月，可负（冲回多估）。"""
    trip = _parse_trip(data)
    if data.get("gate_out") in (None, ""):
        raise DomainIssue("BAD_REQUEST", detail="实结必须提供 gate_out")
    period = data.get("period")
    _validate_period(period)
    container_id = trip["container_id"]
    already = store.booked_cents(container_id)
    request_key = data.get("idempotency_key") or _request_key(
        "SETTLE", c=container_id, p=period, g=trip["gate_in"], o=trip["gate_out"],
        f=trip["free_days"], b=already)
    existing = store.find_by_request(request_key)
    if existing is not None:
        existing["created"] = False
        return existing
    if store.period_status(period)["status"] == "CLOSED":
        raise DomainIssue("PERIOD_CLOSED", 409)
    if any(item["entry_type"] == domain.SETTLEMENT for item in store.list_entries(container_id=container_id)):
        raise DomainIssue("SETTLEMENT_EXISTS", 409)
    try:
        entry = domain.build_settlement_entry(trip, period, already)
    except ValueError as exc:
        raise DomainIssue(str(exc), 400)
    row, created = store.post_entry(entry, request_key)
    row["created"] = created
    return row


def close_period(store, period):
    _validate_period(period)
    row, created = store.close_period(period, _request_key("CLOSE", p=period))
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    row["created"] = created
    return row


def reconcile(store, data):
    """对账：同一趟各历月入账金额合计必须等于整趟实费。"""
    container_id = data.get("container_id")
    if not container_id:
        raise DomainIssue("BAD_REQUEST")
    trip = _parse_trip(data)
    if data.get("gate_out") in (None, ""):
        raise DomainIssue("BAD_REQUEST", detail="对账必须提供 gate_out")
    try:
        actual = domain.actual_fee_cents(
            domain._as_date(trip["gate_in"]), domain._as_date(trip["gate_out"]),
            domain._free_days(trip["free_days"]))
    except ValueError as exc:
        raise DomainIssue(str(exc), 400)
    return store.trip_reconcile(container_id, actual)

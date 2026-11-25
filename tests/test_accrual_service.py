import pytest

from app.accrual.store import AccrualStore
from app.errors import DomainIssue


@pytest.fixture
def store(tmp_path):
    return AccrualStore(tmp_path / "accrual.sqlite3")


TRIP = {"container_id": "C1", "gate_in": "2026-11-02", "free_days": 3}


def accrual(store, period="2026-11", trip=None, key=None):
    from app.accrual.service import post_accrual
    data = dict(TRIP if trip is None else trip)
    data["period"] = period
    if key:
        data["idempotency_key"] = key
    return post_accrual(store, data)


def test_accrual_is_persisted_and_listed(store):
    row = accrual(store)
    assert row["entry_type"] == "ACCRUAL"
    assert row["period"] == "2026-11"
    assert row["created"] is True
    listed = store.list_entries(container_id="C1")
    assert len(listed) == 1
    assert listed[0]["id"] == row["id"]


def test_retry_with_same_key_does_not_double_post(store):
    first = accrual(store, key="fixed-key-1")
    second = accrual(store, key="fixed-key-1")
    assert first["id"] == second["id"]
    assert second["created"] is False
    assert len(store.list_entries(container_id="C1")) == 1


def test_retry_without_key_is_still_idempotent(store):
    # 不传幂等键时由业务要素派生确定性请求键，关账失败重试也不会重复入账
    first = accrual(store)
    second = accrual(store)
    assert first["id"] == second["id"]
    assert len(store.list_entries(container_id="C1")) == 1


def test_second_accrual_in_same_period_is_rejected(store):
    # 同业务要素的裸请求视为重试（幂等）；携带不同幂等键的第二个请求才是重复暂估
    accrual(store)
    from app.accrual.service import post_accrual
    data = dict(TRIP, period="2026-11", idempotency_key="another-request")
    with pytest.raises(DomainIssue) as exc:
        post_accrual(store, data)
    assert exc.value.code == "ENTRY_EXISTS"


def test_closed_period_blocks_new_entries(store):
    from app.accrual.service import close_period
    close_period(store, "2026-11")
    with pytest.raises(DomainIssue) as exc:
        accrual(store)
    assert exc.value.code == "PERIOD_CLOSED"
    assert exc.value.status == 409


def test_close_period_is_idempotent(store):
    from app.accrual.service import close_period
    first = close_period(store, "2026-11")
    second = close_period(store, "2026-11")
    assert first["period"] == second["period"] == "2026-11"
    assert first["status"] == second["status"] == "CLOSED"
    assert second["created"] is False


def test_closed_period_keeps_old_entries_readable(store):
    row = accrual(store)
    from app.accrual.service import close_period
    close_period(store, "2026-11")
    assert store.list_entries(container_id="C1")[0]["id"] == row["id"]
    assert store.booked_cents("C1") == row["amount_cents"]


def test_full_cross_month_over_accrual_reversal(store):
    """核心业务场景：11 月暂估 -> 11 月关账 -> 12 月晚到出港记录证明估多 -> 负向差额入 12 月。"""
    from app.accrual.service import close_period, post_settlement, reconcile
    nov = accrual(store, period="2026-11")
    close_period(store, "2026-11")
    # 关账后不能再改 11 月账：携带新幂等键的写请求被关账期拦截
    with pytest.raises(DomainIssue) as exc:
        accrual(store, period="2026-11", key="write-after-close")
    assert exc.value.code == "PERIOD_CLOSED"
    # 而关账前同一请求的重试仍按幂等返回旧分录，不会因关账而报错或重复入账
    retry = accrual(store, period="2026-11")
    assert retry["id"] == nov["id"]
    assert len(store.list_entries(container_id="C1")) == 1
    # 12 月收到出港记录：实费 52000，低于 11 月末暂估
    settle_data = dict(TRIP, period="2026-12", gate_out="2026-11-10")
    settle = post_settlement(store, settle_data)
    assert settle["entry_type"] == "SETTLEMENT"
    assert settle["period"] == "2026-12"
    assert settle["amount_cents"] < 0
    # 同一趟历月入账金额合计 == 整趟实费
    report = reconcile(store, settle_data)
    assert report["balanced"] is True
    assert report["booked_cents"] == 52000
    assert report["difference_cents"] == 0
    assert len(report["entries"]) == 2


def test_settlement_retry_does_not_double_post(store):
    from app.accrual.service import post_settlement
    accrual(store, period="2026-11")
    data = dict(TRIP, period="2026-12", gate_out="2026-11-10", idempotency_key="sk-1")
    first = post_settlement(store, data)
    second = post_settlement(store, data)
    assert first["id"] == second["id"]
    assert len(store.list_entries(container_id="C1")) == 2


def test_double_settlement_is_rejected(store):
    from app.accrual.service import post_settlement
    accrual(store, period="2026-11")
    post_settlement(store, dict(TRIP, period="2026-12", gate_out="2026-11-10"))
    with pytest.raises(DomainIssue) as exc:
        post_settlement(store, dict(TRIP, period="2026-12", gate_out="2026-11-10"))
    assert exc.value.code == "SETTLEMENT_EXISTS"


def test_settlement_into_closed_period_is_blocked(store):
    from app.accrual.service import close_period, post_settlement
    accrual(store, period="2026-11")
    close_period(store, "2026-12")
    with pytest.raises(DomainIssue) as exc:
        post_settlement(store, dict(TRIP, period="2026-12", gate_out="2026-11-10"))
    assert exc.value.code == "PERIOD_CLOSED"


def test_under_accrual_supplements_positive_delta(store):
    """估少了：实结差额为正，补提后历月累加仍等于实费。"""
    from app.accrual.service import post_settlement, reconcile
    accrual(store, period="2026-11")
    data = dict(TRIP, period="2026-12", gate_out="2026-12-15")
    settle = post_settlement(store, data)
    assert settle["amount_cents"] > 0
    report = reconcile(store, data)
    assert report["balanced"] is True
    assert report["booked_cents"] == report["actual_cents"]


def test_multi_month_accruals_then_settlement_balance(store):
    """连续多个历月暂估（仍在港），最后实结，全程同一条阶梯曲线。"""
    from app.accrual.service import post_settlement, reconcile
    long_trip = {"container_id": "C9", "gate_in": "2026-10-20", "free_days": 0}
    nov = accrual(store, period="2026-11", trip=long_trip)
    dec = accrual(store, period="2026-12", trip=long_trip)
    assert dec["amount_cents"] >= 0
    data = dict(long_trip, period="2027-01", gate_out="2027-01-08")
    settle = post_settlement(store, data)
    report = reconcile(store, data)
    assert report["balanced"] is True
    assert nov["amount_cents"] + dec["amount_cents"] + settle["amount_cents"] == report["actual_cents"]


def test_bad_period_returns_bad_request(store):
    from app.accrual.service import post_accrual
    with pytest.raises(DomainIssue) as exc:
        post_accrual(store, dict(TRIP, period="2026/11"))
    assert exc.value.status == 400


def test_missing_fields_are_rejected(store):
    from app.accrual.service import post_accrual
    with pytest.raises(DomainIssue):
        post_accrual(store, {"container_id": "C1", "period": "2026-11"})

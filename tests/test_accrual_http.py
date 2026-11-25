TRIP = {"container_id": "H1", "gate_in": "2026-11-02", "free_days": 3}


def test_accrual_flow_over_http(client):
    # 11 月暂估
    resp = client.post("/api/accruals/entries", json=dict(TRIP, period="2026-11"))
    assert resp.status_code == 200
    nov = resp.get_json()
    assert nov["entry_type"] == "ACCRUAL"
    assert nov["created"] is True

    # 重试不重复入账
    again = client.post("/api/accruals/entries", json=dict(TRIP, period="2026-11"))
    assert again.get_json()["id"] == nov["id"]
    assert again.get_json()["created"] is False

    # 关账
    closed = client.post("/api/accruals/periods/2026-11/close")
    assert closed.status_code == 200
    assert closed.get_json()["status"] == "CLOSED"
    # 关账重试幂等
    assert client.post("/api/accruals/periods/2026-11/close").get_json()["created"] is False

    # 关账后新写被拒
    blocked = client.post("/api/accruals/entries",
                          json=dict(TRIP, period="2026-11", idempotency_key="new-write"))
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "PERIOD_CLOSED"

    # 12 月晚到出港记录，实费 52000，负向冲回
    settle = client.post("/api/accruals/settlements",
                         json=dict(TRIP, period="2026-12", gate_out="2026-11-10"))
    assert settle.status_code == 200
    body = settle.get_json()
    assert body["entry_type"] == "SETTLEMENT"
    assert body["amount_cents"] < 0

    # 对账：历月累加 == 整趟实费
    report = client.post("/api/accruals/reconcile",
                         json=dict(TRIP, period="2026-12", gate_out="2026-11-10")).get_json()
    assert report["balanced"] is True
    assert report["booked_cents"] == 52000
    assert report["difference_cents"] == 0
    assert len(report["entries"]) == 2


def test_list_entries_and_periods(client):
    client.post("/api/accruals/entries", json=dict(TRIP, period="2026-11"))
    client.post("/api/accruals/periods/2026-11/close")
    entries = client.get("/api/accruals/entries?container_id=H1").get_json()
    assert len(entries) == 1
    assert client.get("/api/accruals/periods").get_json()[0]["period"] == "2026-11"


def test_bad_period_returns_400(client):
    resp = client.post("/api/accruals/entries", json=dict(TRIP, period="2026/11"))
    assert resp.status_code == 400


def test_settlement_requires_gate_out(client):
    resp = client.post("/api/accruals/settlements", json=dict(TRIP, period="2026-12"))
    assert resp.status_code == 400


def test_double_settlement_is_conflict(client):
    client.post("/api/accruals/entries", json=dict(TRIP, period="2026-11"))
    payload = dict(TRIP, period="2026-12", gate_out="2026-11-10")
    first = client.post("/api/accruals/settlements", json=payload)
    second = client.post("/api/accruals/settlements",
                         json=dict(payload, idempotency_key="different"))
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["code"] == "SETTLEMENT_EXISTS"


def test_explicit_idempotency_key_retry(client):
    payload = dict(TRIP, period="2026-11", idempotency_key="batch-001")
    first = client.post("/api/accruals/entries", json=payload).get_json()
    second = client.post("/api/accruals/entries", json=payload).get_json()
    assert first["id"] == second["id"]


def test_malformed_inputs_are_400_not_500(client):
    bad_date = client.post("/api/accruals/entries",
                           json=dict(TRIP, period="2026-11", gate_in="not-a-date"))
    assert bad_date.status_code == 400
    assert bad_date.get_json()["code"] == "BAD_DATE"
    bad_days = client.post("/api/accruals/entries",
                           json=dict(TRIP, period="2026-11", free_days="abc"))
    assert bad_days.status_code == 400
    assert bad_days.get_json()["code"] == "BAD_FREE_DAYS"
    negative_days = client.post("/api/accruals/entries",
                                json=dict(TRIP, period="2026-11", free_days=-1))
    assert negative_days.status_code == 400
    assert negative_days.get_json()["code"] == "BAD_FREE_DAYS"
    gate_order = client.post("/api/accruals/settlements",
                             json=dict(TRIP, period="2026-12", gate_out="2026-10-01"))
    assert gate_order.status_code == 400
    assert gate_order.get_json()["code"] == "GATE_ORDER"
    not_arrived = client.post("/api/accruals/entries",
                              json=dict(TRIP, period="2026-10", gate_in="2026-11-02"))
    assert not_arrived.status_code == 400
    assert not_arrived.get_json()["code"] == "TRIP_NOT_ARRIVED"

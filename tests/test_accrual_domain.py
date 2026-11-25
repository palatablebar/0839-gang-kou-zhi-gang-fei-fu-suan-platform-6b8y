from datetime import date

import pytest

from app.accrual import domain
from app.accrual.domain import (ACCRUAL, SETTLEMENT, accrual_fee_cents,
                                actual_fee_cents, build_accrual_entry,
                                build_settlement_entry, charge_days_until,
                                free_deadline, month_end, reconcile_trip)
from app.domain.helpers import tier_fee


def test_month_end_covers_all_calendar_months():
    assert month_end("2026-02") == date(2026, 2, 28)
    assert month_end("2024-02") == date(2024, 2, 29)  # 闰年
    assert month_end("2026-04") == date(2026, 4, 30)
    assert month_end("2026-12") == date(2026, 12, 31)


def test_bad_period_is_rejected():
    for bad in ("2026/11", "2026-13", "abc", "", "26-1"):
        with pytest.raises(ValueError):
            month_end(bad)


def test_free_deadline_matches_calculate_layer():
    # 与 test_calculate.py 的边界用例同一口径：2026-11-02 进港、3 个免堆工作日
    deadline = free_deadline(date(2026, 11, 2), 3)
    # 11/3、11/4、11/5 三个工作日 -> 截止 11/5；11/6 出港产生 1 个计费日
    assert deadline == date(2026, 11, 5)
    assert charge_days_until(date(2026, 11, 2), 3, date(2026, 11, 5)) == 1
    assert tier_fee(1) == 8000


def test_tier_does_not_reset_across_months():
    # 跨月后继续沿用同一趟的阶梯费率：累计 10 个计费日 = 3*8000 + 5*14000 + 2*22000
    assert tier_fee(10) == 3 * 8000 + 5 * 14000 + 2 * 22000
    # 两个月末各自的累计应计必须都落在同一条阶梯曲线上，而不是每月重新从第一档起算
    gate_in, free_days = date(2026, 10, 20), 0
    nov = accrual_fee_cents(gate_in, free_days, "2026-11")
    dec = accrual_fee_cents(gate_in, free_days, "2026-12")
    assert nov == tier_fee(charge_days_until(gate_in, free_days, month_end("2026-11")))
    assert dec >= nov
    assert dec == tier_fee(charge_days_until(gate_in, free_days, month_end("2026-12")))


def test_accrual_is_zero_inside_free_period():
    # 进港即进入免堆期，月末仍未超免堆截止 -> 暂估为 0
    gate_in = date(2026, 11, 25)
    assert accrual_fee_cents(gate_in, 30, "2026-11") == 0


def test_accrual_entry_is_delta_against_already_booked():
    trip = {"container_id": "X1", "gate_in": date(2026, 10, 20), "free_days": 0}
    nov = build_accrual_entry(trip, "2026-11", already_booked=0)
    assert nov["entry_type"] == ACCRUAL
    dec = build_accrual_entry(trip, "2026-12", already_booked=nov["cumulative_cents"])
    # 12 月分录是增量，累计应计保持同一条阶梯曲线
    assert dec["amount_cents"] == dec["cumulative_cents"] - nov["cumulative_cents"]
    assert nov["amount_cents"] + dec["amount_cents"] == dec["cumulative_cents"]


def test_settlement_negative_entry_reverses_over_accrual():
    # 场景：11 月底仍在港，按月末口径暂估；12 月才收到 11 月末附近的出港记录，实费更低
    trip = {"container_id": "X2", "gate_in": date(2026, 11, 2), "free_days": 3}
    accrued = build_accrual_entry(trip, "2026-11", already_booked=0)
    # 真实出港 11/10（与 clean 样例 C1 同口径，5 个计费日 -> 52000）
    settled_trip = dict(trip, gate_out=date(2026, 11, 10))
    actual = actual_fee_cents(settled_trip["gate_in"], settled_trip["gate_out"], 3)
    assert actual == 52000
    assert accrued["cumulative_cents"] > actual  # 月末口径确实估多了
    settle = build_settlement_entry(settled_trip, "2026-12", already_booked=accrued["cumulative_cents"])
    assert settle["entry_type"] == SETTLEMENT
    assert settle["amount_cents"] < 0  # 差额冲回，本月负向调整
    result = reconcile_trip(
        [{"amount_cents": accrued["amount_cents"]}, {"amount_cents": settle["amount_cents"]}], actual)
    assert result["balanced"] is True
    assert result["difference_cents"] == 0


def test_settlement_positive_entry_supplements_under_accrual():
    trip = {"container_id": "X3", "gate_in": date(2026, 11, 2), "free_days": 3}
    accrued = build_accrual_entry(trip, "2026-11", already_booked=0)
    settled_trip = dict(trip, gate_out=date(2026, 12, 15))
    actual = actual_fee_cents(settled_trip["gate_in"], settled_trip["gate_out"], 3)
    settle = build_settlement_entry(settled_trip, "2026-12", already_booked=accrued["cumulative_cents"])
    assert settle["amount_cents"] > 0
    assert accrued["amount_cents"] + settle["amount_cents"] == actual
    assert reconcile_trip(
        [{"amount_cents": accrued["amount_cents"]}, {"amount_cents": settle["amount_cents"]}],
        actual)["balanced"] is True


def test_exact_settlement_has_zero_delta():
    trip = {"container_id": "X4", "gate_in": date(2026, 11, 2), "free_days": 3,
            "gate_out": date(2026, 11, 10)}
    # 出港日恰为月末口径虚拟出港日（次月 1 号）时，暂估与实费天然相等
    accrued = build_accrual_entry(
        {k: v for k, v in trip.items() if k != "gate_out"}, "2026-11", 0)
    actual = actual_fee_cents(trip["gate_in"], trip["gate_out"], trip["free_days"])
    assert accrued["cumulative_cents"] != actual  # 月末在港口径通常高于提前出港
    settle = build_settlement_entry(trip, "2026-12", already_booked=actual)
    assert settle["amount_cents"] == 0
    assert reconcile_trip(
        [{"amount_cents": actual}, {"amount_cents": 0}], actual)["balanced"] is True


def test_settlement_rejects_gate_order():
    trip = {"container_id": "X5", "gate_in": date(2026, 11, 10),
            "gate_out": date(2026, 11, 2), "free_days": 3}
    with pytest.raises(ValueError):
        build_settlement_entry(trip, "2026-11", 0)


def test_accrual_rejects_trip_not_arrived():
    trip = {"container_id": "X6", "gate_in": date(2026, 12, 5), "free_days": 3}
    with pytest.raises(ValueError):
        build_accrual_entry(trip, "2026-11", 0)


def test_month_end_day_itself_counts_as_in_port():
    # 免堆截止 11/5，月末 11/30 仍在港：11/6..11/30 共 25 天，
    # 虚拟出港日为 12/1，(12/1 - 11/5).days = 26 个计费日（月末当天也计一天）
    assert charge_days_until(date(2026, 11, 2), 3, date(2026, 11, 30)) == 26
    assert accrual_fee_cents(date(2026, 11, 2), 3, "2026-11") == tier_fee(26)


def test_holidays_apply_inside_free_window_across_months():
    # 国庆假日 10/1-10/7，10/8 复工；2026-09-29 进港、3 个免堆工作日
    # -> 9/30(周三)、10/8(周四)、10/9(周五)，截止 10/9
    deadline = free_deadline(date(2026, 9, 29), 3)
    assert deadline == date(2026, 10, 9)
    # clean 样例 C3：10/12 出港 -> 3 个计费日（3*8000=24000），与复算层一致
    assert actual_fee_cents(date(2026, 9, 29), date(2026, 10, 12), 3) == 24000

"""跨月滞港费暂估入账域。

规则要点：
- 月底仍未出港的箱子，按截至月末已产生的滞港费暂估入账。
- 跨月继续沿用这一趟原有的免堆期与同一套阶梯费率（阶梯不跨月重置）。
- 关账后旧账不能改：晚到的出港记录若证明上月估多了，差额以负向调整计入本月。
- 同一趟各历月入账金额之和必须等于整趟实费。
所有金额以整数最小单位（分）表示，避免浮点漂移。
"""
from datetime import date

from app.domain.calendar import holidays_for
from app.domain.helpers import DAY, I, business_days_after, tier_fee

ACCRUAL = "ACCRUAL"
SETTLEMENT = "SETTLEMENT"


def _free_days(value) -> int:
    try:
        number = I(value, "BAD_FREE_DAYS")
    except ValueError:
        raise ValueError("BAD_FREE_DAYS")
    if number < 0:
        raise ValueError("BAD_FREE_DAYS")
    return number


def month_end(period: str) -> date:
    """'YYYY-MM' -> 该月最后一天（次月 1 号退一天，免手写各月天数）。"""
    year, month = _split_period(period)
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    return date.fromordinal(next_first.toordinal() - 1)


def _split_period(period: str) -> tuple[int, int]:
    try:
        year_text, month_text = str(period).split("-")
        year, month = int(year_text), int(month_text)
    except (ValueError, AttributeError):
        raise ValueError("BAD_PERIOD")
    if not 1 <= month <= 12 or year < 1900 or year > 9999:
        raise ValueError("BAD_PERIOD")
    return year, month


def validate_period(period: str) -> str:
    _split_period(period)
    return period


def free_deadline(gate_in: date, free_days: int) -> date:
    """一趟箱子的免堆截止日，跨月暂估与最终实结共用同一口径。"""
    return business_days_after(gate_in, free_days, holidays_for(gate_in))


def charge_days_until(gate_in: date, free_days: int, cutoff: date) -> int:
    """截至 cutoff（含当日在港）已产生的计费天数。

    与复算层保持同一约定：charge_days = max(0, (虚拟出港日 - 免堆截止).days)，
    月末仍在港时用次月 1 号作为虚拟出港日，即月末当天也计一天。
    """
    deadline = free_deadline(gate_in, free_days)
    virtual_gate_out = date.fromordinal(cutoff.toordinal() + 1)
    return max(0, (virtual_gate_out - deadline).days)


def accrual_fee_cents(gate_in: date, free_days: int, period: str) -> int:
    """截至某历月月末的累计应计滞港费（同一套阶梯，跨月不重置）。"""
    days = charge_days_until(gate_in, free_days, month_end(period))
    return tier_fee(days)


def actual_fee_cents(gate_in: date, gate_out: date, free_days: int) -> int:
    """整趟实费，口径与复算层 calculate_rows 完全一致。"""
    deadline = free_deadline(gate_in, free_days)
    return tier_fee(max(0, (gate_out - deadline).days))


def build_accrual_entry(trip: dict, period: str, already_booked: int) -> dict:
    """生成某历月的暂估入账分录（差额入账，保证历月累加等于当前累计应计）。

    trip 至少包含 container_id / gate_in / free_days；gate_out 缺失表示仍在港。
    already_booked 为该趟在本历月之前已经入账的金额合计（分）。
    """
    gate_in = _as_date(trip["gate_in"])
    free_days = _free_days(trip["free_days"])
    cutoff = month_end(period)
    if gate_in > cutoff:
        raise ValueError("TRIP_NOT_ARRIVED")
    cumulative = accrual_fee_cents(gate_in, free_days, period)
    amount = cumulative - int(already_booked)
    return {
        "container_id": str(trip["container_id"]),
        "period": validate_period(period),
        "entry_type": ACCRUAL,
        "amount_cents": amount,
        "cumulative_cents": cumulative,
        "charge_days": charge_days_until(gate_in, free_days, cutoff),
    }


def build_settlement_entry(trip: dict, period: str, already_booked: int) -> dict:
    """出港后实结：把整趟实费与历月已入账合计的差额计入本历月。

    差额可正可负：上月估多了就是负向调整，冲回多收部分；估少了则补提。
    """
    gate_in = _as_date(trip["gate_in"])
    gate_out = _as_date(trip["gate_out"])
    free_days = _free_days(trip["free_days"])
    if gate_out < gate_in:
        raise ValueError("GATE_ORDER")
    deadline = free_deadline(gate_in, free_days)
    charge_days = max(0, (gate_out - deadline).days)
    actual = tier_fee(charge_days)
    amount = actual - int(already_booked)
    return {
        "container_id": str(trip["container_id"]),
        "period": validate_period(period),
        "entry_type": SETTLEMENT,
        "amount_cents": amount,
        "cumulative_cents": actual,
        "charge_days": charge_days,
    }


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return DAY(value, "BAD_DATE")


def reconcile_trip(entries: list[dict], actual_cents: int) -> dict:
    """同一趟历月入账金额合计对账：必须等于整趟实费。"""
    booked = sum(int(entry["amount_cents"]) for entry in entries)
    return {
        "booked_cents": booked,
        "actual_cents": int(actual_cents),
        "difference_cents": int(actual_cents) - booked,
        "balanced": booked == int(actual_cents),
    }

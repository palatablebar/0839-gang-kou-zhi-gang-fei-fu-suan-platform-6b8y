from datetime import date

# 法定假日（本地工作台内置日历，复算与跨月暂估共用，保证同一趟历月口径一致）
HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    *{date(2026, 10, d) for d in range(1, 8)},
}


def holidays_for(day: date) -> set[date]:
    """返回覆盖给定日期的节假日集合。当前工作台只内置 2026 年日历。"""
    return set(HOLIDAYS_2026)

from flask import jsonify


MESSAGES = {
    "EMPTY_FILE": "文件为空",
    "BLANK_FILE": "文件只有空白",
    "HEADER_ONLY": "文件只有表头",
    "HEADER_MISMATCH": "表头与本项目字段不一致",
    "UNCLOSED_QUOTE": "引号未闭合，文件已拒收",
    "TOO_MANY_ROWS": "数据行超过上限",
    "FILE_TOO_LARGE": "文件超过大小上限",
    "KEY_MISSING": "主键为空",
    "CONFLICT_DUPLICATE": "同一键存在冲突内容",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "阶段不存在",
    "RUN_NOT_FOUND": "批次不存在",
    "STALE_REVIEW": "批次已被更新，请刷新后复核",
    "GATE_BLOCKED": "存在阻断项，不能签发",
    "NOT_APPROVED": "批次尚未签发",
    "BAD_REQUEST": "请求内容不完整",
    "PERIOD_CLOSED": "该历月已关账，旧账不能修改",
    "ENTRY_EXISTS": "该历月已有暂估分录，不能重复暂估",
    "SETTLEMENT_EXISTS": "该趟已实结，不能重复实结",
    "TRIP_NOT_ARRIVED": "箱子在该历月末尚未进港，无需暂估",
    "BAD_PERIOD": "历月格式应为 YYYY-MM",
    "BAD_DATE": "日期格式应为 YYYY-MM-DD",
    "BAD_FREE_DAYS": "免堆工作日必须是非负整数",
    "GATE_ORDER": "出港日期不能早于进港日期",
}


class DomainIssue(Exception):
    def __init__(self, code: str, status: int = 400, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(code)


def error_response(exc: DomainIssue):
    return jsonify(error=exc.detail or MESSAGES.get(exc.code, "请求无法处理"), code=exc.code), exc.status

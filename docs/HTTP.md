# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据。
- `GET /api/examples/{profile}`：下载样例。
- `POST /api/accruals/entries`：月末暂估入账，提交 `container_id`、`gate_in`、`free_days`、`period`，可选 `idempotency_key`。
- `POST /api/accruals/settlements`：出港实结，追加 `gate_out`；差额（可为负）计入 `period`。
- `POST /api/accruals/periods/{period}/close`：历月关账，重复调用幂等。
- `GET /api/accruals/periods`：历月关账状态。
- `GET /api/accruals/entries?container_id=&period=`：查询分录。
- `POST /api/accruals/reconcile`：按趟对账，返回历月入账合计、整趟实费与差额。
- `GET /healthz`：健康检查。

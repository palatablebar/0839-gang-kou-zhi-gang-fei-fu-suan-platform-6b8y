# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `container_id` | text | 主键 |
| `gate_in` | date | 业务字段 |
| `gate_out` | date | 业务字段 |
| `free_days` | int | 业务字段 |
| `invoice_cents` | int | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 跨月暂估分录（accrual_entries）

| 字段 | 类型 | 说明 |
|---|---|---|
| `container_id` | text | 趟次主键，同一箱子的历月分录共享 |
| `period` | text | 入账历月，格式 `YYYY-MM` |
| `entry_type` | text | `ACCRUAL` 月末暂估 / `SETTLEMENT` 出港实结 |
| `amount_cents` | int | 本次入账金额（分），实结冲回时为负 |
| `cumulative_cents` | int | 截至该历月同一阶梯曲线上的累计金额（分） |
| `charge_days` | int | 截至历月末（暂估）或出港日（实结）的计费天数 |
| `request_key` | text | 幂等键，唯一约束，重试命中即返回原分录 |

历月状态表 `periods` 记录 `OPEN`/`CLOSED`；关账后该历月拒绝任何新分录（`PERIOD_CLOSED`）。

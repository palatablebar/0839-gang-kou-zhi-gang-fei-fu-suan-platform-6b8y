import sqlite3
import uuid
from datetime import datetime, timezone

from app.errors import DomainIssue

OPEN = "OPEN"
CLOSED = "CLOSED"


class AccrualStore:
    """跨月暂估入账存储。

    - periods：历月关账状态，关账后旧账不能改、不能再补分录。
    - accrual_entries：按趟（container_id）记录各历月分录，amount 可为负（冲回）。
    - request_key 唯一约束保证关账/入账失败重试不会重复入账。
    """

    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS periods(
              period TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'OPEN',
              closed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS accrual_entries(
              id TEXT PRIMARY KEY,
              request_key TEXT UNIQUE NOT NULL,
              container_id TEXT NOT NULL,
              period TEXT NOT NULL,
              entry_type TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              cumulative_cents INTEGER NOT NULL,
              charge_days INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_entries_trip ON accrual_entries(container_id);
            ''')

    # ---- 历月关账 -------------------------------------------------------
    def period_status(self, period):
        with self.connect() as db:
            row = db.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
        return dict(row) if row else {"period": period, "status": OPEN, "closed_at": None}

    def close_period(self, period, request_key):
        """关账。已关账的重复请求按幂等返回，不产生副作用。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
            if existing is not None:
                return dict(existing), False
            closed_at = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO periods(period,status,closed_at) VALUES(?,?,?)",
                       (period, CLOSED, closed_at))
        return self.period_status(period), True

    def _ensure_open(self, db, period):
        row = db.execute("SELECT status FROM periods WHERE period=?", (period,)).fetchone()
        if row is not None and row["status"] == CLOSED:
            raise DomainIssue("PERIOD_CLOSED", 409)

    # ---- 入账 -----------------------------------------------------------
    def post_entry(self, entry, request_key, detail=""):
        """写入一条分录。request_key 冲突时返回原分录，保证失败重试不重复入账。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM accrual_entries WHERE request_key=?", (request_key,)).fetchone()
            if existing is not None:
                return dict(existing), False
            self._ensure_open(db, entry["period"])
            entry_id = uuid.uuid4().hex[:12]
            db.execute(
                "INSERT INTO accrual_entries(id,request_key,container_id,period,entry_type,"
                "amount_cents,cumulative_cents,charge_days,created_at,detail) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (entry_id, request_key, entry["container_id"], entry["period"], entry["entry_type"],
                 int(entry["amount_cents"]), int(entry["cumulative_cents"]), int(entry["charge_days"]),
                 datetime.now(timezone.utc).isoformat(), detail),
            )
        return self.get_entry(entry_id), True

    def get_entry(self, entry_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM accrual_entries WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def find_by_request(self, request_key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM accrual_entries WHERE request_key=?",
                             (request_key,)).fetchone()
        return dict(row) if row else None

    def booked_cents(self, container_id, before_period=None):
        """某趟已入账金额合计；before_period 给定时只统计更早历月（关账旧账只读）。"""
        with self.connect() as db:
            if before_period is None:
                rows = db.execute(
                    "SELECT COALESCE(SUM(amount_cents),0) AS total FROM accrual_entries WHERE container_id=?",
                    (container_id,)).fetchall()
            else:
                rows = db.execute(
                    "SELECT COALESCE(SUM(amount_cents),0) AS total FROM accrual_entries "
                    "WHERE container_id=? AND period<?", (container_id, before_period)).fetchall()
        return int(rows[0]["total"])

    def list_entries(self, container_id=None, period=None):
        sql = "SELECT * FROM accrual_entries WHERE 1=1"
        params = []
        if container_id is not None:
            sql += " AND container_id=?"
            params.append(container_id)
        if period is not None:
            sql += " AND period=?"
            params.append(period)
        sql += " ORDER BY period ASC, created_at ASC, id ASC"
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_periods(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM periods ORDER BY period ASC").fetchall()
        return [dict(row) for row in rows]

    def trip_reconcile(self, container_id, actual_cents):
        entries = self.list_entries(container_id=container_id)
        booked = sum(int(row["amount_cents"]) for row in entries)
        return {
            "container_id": container_id,
            "entries": entries,
            "booked_cents": booked,
            "actual_cents": int(actual_cents),
            "difference_cents": int(actual_cents) - booked,
            "balanced": booked == int(actual_cents),
        }

    def export_diagnostic(self):
        return {"periods": self.list_periods(), "entries": self.list_entries()}

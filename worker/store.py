import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS vendors(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inbox(
                    id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, issued_at TEXT NOT NULL,
                    subject TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, goal TEXT NOT NULL, mode TEXT NOT NULL,
                    status TEXT NOT NULL, memory TEXT NOT NULL, summary TEXT NOT NULL,
                    steps INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals(
                    task_id TEXT NOT NULL, fingerprint TEXT NOT NULL, decision TEXT NOT NULL,
                    reviewer TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, fingerprint));
                CREATE TABLE IF NOT EXISTS records(
                    id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, invoice_number TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(vendor_id, invoice_number));
                CREATE TABLE IF NOT EXISTS faults(name TEXT PRIMARY KEY, remaining INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def seed(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "company.json").read_text())
        with self.connect() as db:
            for vendor in fixture["vendors"]:
                db.execute("INSERT OR IGNORE INTO vendors VALUES(:id,:name)", vendor)
            for invoice in fixture["invoices"]:
                db.execute(
                    "INSERT OR IGNORE INTO inbox VALUES(:id,:vendor_id,:issued_at,:subject,:body)", invoice
                )

    def create_task(self, goal, mode):
        task_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,0,?,?)",
                (task_id, goal, mode, "pending", "{}", "", now(), now()),
            )
        self.event(task_id, "created", {"goal": goal, "mode": mode})
        return self.task(task_id)

    def task(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        task = dict(row)
        task["memory"] = json.loads(task["memory"])
        return task

    def save(self, task):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET goal=?,status=?,memory=?,summary=?,steps=?,updated_at=? WHERE id=?",
                (
                    task["goal"],
                    task["status"],
                    json.dumps(task["memory"]),
                    task["summary"],
                    task["steps"],
                    now(),
                    task["id"],
                ),
            )

    def event(self, task_id, kind, data):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(task_id,kind,data,created_at) VALUES(?,?,?,?)",
                (task_id, kind, json.dumps(data), now()),
            )

    def events(self, task_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE task_id=? ORDER BY seq", (task_id,)).fetchall()
        return [dict(row) | {"data": json.loads(row["data"])} for row in rows]

    def rows(self, table):
        if table not in {"vendors", "inbox", "records", "tasks", "approvals"}:
            raise ValueError("Unknown table")
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]

    def source(self, source_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM inbox WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        return dict(row)

    def consume_fault(self, name):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE faults SET remaining=remaining-1 WHERE name=? AND remaining>0", (name,)
            ).rowcount
        return bool(changed)

    def recover(self):
        # A human may resume these tasks. Never silently replay an interrupted external action.
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='interrupted' WHERE status IN ('running','pending')")

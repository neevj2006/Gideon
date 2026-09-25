from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS todos (id TEXT PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', due_at TEXT, priority INTEGER NOT NULL DEFAULT 2 CHECK(priority BETWEEN 1 AND 3), completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, text TEXT NOT NULL, due_at TEXT NOT NULL, recurrence TEXT, state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body, content='notes', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN INSERT INTO notes_fts(rowid,title,body) VALUES(new.rowid,new.title,new.body); END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN INSERT INTO notes_fts(notes_fts,rowid,title,body) VALUES('delete',old.rowid,old.title,old.body); END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN INSERT INTO notes_fts(notes_fts,rowid,title,body) VALUES('delete',old.rowid,old.title,old.body); INSERT INTO notes_fts(rowid,title,body) VALUES(new.rowid,new.title,new.body); END;
CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, topic TEXT NOT NULL UNIQUE, value TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversation (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS confirmations (id TEXT PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL, summary TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE IF NOT EXISTS phone_devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, secret_name TEXT NOT NULL, paired_at TEXT NOT NULL, last_seen_at TEXT);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = str(path)
        self._lock = threading.RLock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as db:
            cur = db.execute(sql, params)
            return [dict(row) for row in cur.fetchall()] if cur.description else []

    def add_todo(self, title: str, due_at: str | None = None, priority: int = 2) -> str:
        item_id, now = uuid.uuid4().hex[:8], now_iso()
        self.execute(
            "INSERT INTO todos(id,title,due_at,priority,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (item_id, title, due_at, priority, now, now),
        )
        return item_id

    def list_todos(self, include_done: bool = False) -> list[dict[str, Any]]:
        where = "" if include_done else "WHERE completed_at IS NULL"
        return self.execute(f"SELECT * FROM todos {where} ORDER BY priority,due_at IS NULL,due_at,created_at")

    def update_todo(self, item_id: str, **fields: Any) -> bool:
        values = {
            k: v for k, v in fields.items() if k in {"title", "details", "due_at", "priority", "completed_at"}
        }
        if not values:
            return False
        values["updated_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in values)
        with self.connection() as db:
            cur = db.execute(f"UPDATE todos SET {sets} WHERE id=?", (*values.values(), item_id))
            return cur.rowcount > 0

    def delete_todo(self, item_id: str) -> bool:
        with self.connection() as db:
            return db.execute("DELETE FROM todos WHERE id=?", (item_id,)).rowcount > 0

    def add_reminder(self, text: str, due_at: str, recurrence: str | None = None) -> str:
        item_id = uuid.uuid4().hex[:8]
        self.execute(
            "INSERT INTO reminders(id,text,due_at,recurrence,created_at) VALUES(?,?,?,?,?)",
            (item_id, text, due_at, recurrence, now_iso()),
        )
        return item_id

    def list_reminders(self) -> list[dict[str, Any]]:
        return self.execute("SELECT * FROM reminders WHERE state='active' ORDER BY due_at")

    def due_reminders(self) -> list[dict[str, Any]]:
        return self.execute(
            "SELECT * FROM reminders WHERE state='active' AND due_at<=? ORDER BY due_at", (now_iso(),)
        )

    def update_reminder(self, item_id: str, **fields: Any) -> bool:
        values = {k: v for k, v in fields.items() if k in {"text", "due_at", "recurrence", "state"}}
        if not values:
            return False
        with self.connection() as db:
            cur = db.execute(
                f"UPDATE reminders SET {','.join(f'{k}=?' for k in values)} WHERE id=?",
                (*values.values(), item_id),
            )
            return cur.rowcount > 0

    def delete_reminder(self, item_id: str) -> bool:
        with self.connection() as db:
            return db.execute("DELETE FROM reminders WHERE id=?", (item_id,)).rowcount > 0

    def add_note(self, title: str, body: str) -> str:
        item_id, now = uuid.uuid4().hex[:8], now_iso()
        self.execute(
            "INSERT INTO notes(id,title,body,created_at,updated_at) VALUES(?,?,?,?,?)",
            (item_id, title, body, now, now),
        )
        return item_id

    def search_notes(self, query: str = "") -> list[dict[str, Any]]:
        if not query:
            return self.execute("SELECT * FROM notes ORDER BY updated_at DESC")
        safe = " ".join(f'"{word}"' for word in query.split())
        return self.execute(
            "SELECT n.* FROM notes_fts f JOIN notes n ON n.rowid=f.rowid WHERE notes_fts MATCH ? ORDER BY rank",
            (safe,),
        )

    def update_note(self, item_id: str, title: str | None = None, body: str | None = None) -> bool:
        values = {k: v for k, v in {"title": title, "body": body}.items() if v is not None}
        values["updated_at"] = now_iso()
        with self.connection() as db:
            return (
                db.execute(
                    f"UPDATE notes SET {','.join(f'{k}=?' for k in values)} WHERE id=?",
                    (*values.values(), item_id),
                ).rowcount
                > 0
            )

    def delete_note(self, item_id: str) -> bool:
        with self.connection() as db:
            return db.execute("DELETE FROM notes WHERE id=?", (item_id,)).rowcount > 0

    def remember(self, topic: str, value: str) -> None:
        now = now_iso()
        self.execute(
            "INSERT INTO memories(id,topic,value,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(topic) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (uuid.uuid4().hex[:8], topic.lower().strip(), value.strip(), now, now),
        )

    def memories(self, query: str = "") -> list[dict[str, Any]]:
        return self.execute(
            "SELECT * FROM memories WHERE topic LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
            (f"%{query.lower()}%", f"%{query}%"),
        )

    def forget(self, query: str) -> int:
        with self.connection() as db:
            return db.execute(
                "DELETE FROM memories WHERE topic LIKE ? OR value LIKE ?", (f"%{query}%", f"%{query}%")
            ).rowcount

    def forget_ids(self, item_ids: list[str]) -> int:
        if not item_ids:
            return 0
        placeholders = ",".join("?" for _ in item_ids)
        with self.connection() as db:
            return db.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", tuple(item_ids)).rowcount

    def add_turn(self, role: str, text: str) -> None:
        self.execute("INSERT INTO conversation(role,text,created_at) VALUES(?,?,?)", (role, text, now_iso()))
        self.execute(
            "DELETE FROM conversation WHERE id NOT IN (SELECT id FROM conversation ORDER BY id DESC LIMIT 40)"
        )

    def recent_turns(self, limit: int = 8) -> list[dict[str, Any]]:
        return list(
            reversed(self.execute("SELECT role,text FROM conversation ORDER BY id DESC LIMIT ?", (limit,)))
        )

    def create_confirmation(self, action: str, payload: dict[str, Any], summary: str) -> str:
        token = uuid.uuid4().hex[:8]
        expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        self.execute(
            "INSERT INTO confirmations(id,action,payload,summary,expires_at) VALUES(?,?,?,?,?)",
            (token, action, json.dumps(payload), summary, expires),
        )
        return token

    def consume_confirmation(self, token: str | None = None) -> dict[str, Any] | None:
        if token:
            rows = self.execute(
                "SELECT * FROM confirmations WHERE id=? AND used_at IS NULL AND expires_at>?",
                (token, now_iso()),
            )
        else:
            rows = self.execute(
                "SELECT * FROM confirmations WHERE used_at IS NULL AND expires_at>? ORDER BY rowid DESC LIMIT 1",
                (now_iso(),),
            )
        if not rows:
            return None
        row = rows[0]
        self.execute(
            "UPDATE confirmations SET used_at=? WHERE id=? AND used_at IS NULL", (now_iso(), row["id"])
        )
        row["payload"] = json.loads(row["payload"])
        return row

    def cancel_confirmation(self) -> bool:
        rows = self.execute(
            "SELECT id FROM confirmations WHERE used_at IS NULL AND expires_at>? ORDER BY rowid DESC LIMIT 1",
            (now_iso(),),
        )
        if not rows:
            return False
        self.execute("UPDATE confirmations SET used_at=? WHERE id=?", (now_iso(), rows[0]["id"]))
        return True

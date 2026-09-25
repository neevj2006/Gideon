from datetime import UTC, datetime, timedelta

from gideon.db import Database


def test_todo_crud(database: Database) -> None:
    item_id = database.add_todo("ship v1", priority=1)
    assert database.list_todos()[0]["title"] == "ship v1"
    assert database.update_todo(item_id, title="ship v1 today")
    assert database.update_todo(item_id, completed_at=datetime.now(UTC).isoformat())
    assert database.list_todos() == []
    assert database.delete_todo(item_id)


def test_notes_full_text_search(database: Database) -> None:
    item_id = database.add_note("Project Gideon", "local-first assistant")
    assert database.search_notes("local")[0]["id"] == item_id
    assert database.update_note(item_id, body="headless assistant")
    assert database.search_notes("headless")[0]["id"] == item_id
    assert database.delete_note(item_id)


def test_explicit_memory(database: Database) -> None:
    database.remember("coffee", "black")
    database.remember("coffee", "black, no sugar")
    assert database.memories("coffee")[0]["value"] == "black, no sugar"
    assert database.forget("coffee") == 1


def test_confirmation_single_use_and_exact_payload(database: Database) -> None:
    token = database.create_confirmation("send", {"to": "a@example.com", "body": "exact"}, "send exact")
    pending = database.consume_confirmation(token)
    assert pending is not None and pending["payload"]["body"] == "exact"
    assert database.consume_confirmation(token) is None


def test_expired_confirmation_rejected(database: Database) -> None:
    token = database.create_confirmation("delete", {"id": "1"}, "delete")
    database.execute(
        "UPDATE confirmations SET expires_at=? WHERE id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), token),
    )
    assert database.consume_confirmation(token) is None

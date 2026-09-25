from unittest.mock import Mock

from gideon.assistant import Gideon
from gideon.db import Database


def test_local_workflow_and_confirmation(assistant: Gideon, database: Database) -> None:
    added = assistant.handle("add a task buy milk")
    item_id = database.list_todos()[0]["id"]
    assert "added" in added.text
    pending = assistant.handle(f"delete task {item_id}")
    assert pending.needs_confirmation
    assert database.list_todos()
    confirmed = assistant.handle("confirm")
    assert "deleted" in confirmed.text
    assert not database.list_todos()


def test_cancel_invalidates_pending_action(assistant: Gideon, database: Database) -> None:
    item_id = database.add_todo("keep me")
    assistant.handle(f"delete task {item_id}")
    assistant.handle("cancel that")
    assert "no unexpired" in assistant.handle("confirm").text
    assert database.list_todos()[0]["id"] == item_id


def test_forget_confirmation_binds_exact_memory_ids(assistant: Gideon, database: Database) -> None:
    database.remember("coffee", "black")
    assistant.handle("forget coffee")
    database.remember("coffee shop", "newly added")
    assistant.handle("confirm")
    assert database.memories("coffee")[0]["topic"] == "coffee shop"


def test_email_is_not_sent_without_confirmation(assistant: Gideon) -> None:
    assistant.gmail.send = Mock(return_value="message-1")  # type: ignore[method-assign]
    pending = assistant.handle("send email to test@example.com subject Hello body Test body")
    assert pending.needs_confirmation
    assistant.gmail.send.assert_not_called()
    result = assistant.handle("confirm")
    assert "sent" in result.text
    assistant.gmail.send.assert_called_once_with("test@example.com", "Hello", "Test body", "personal", None)


def test_email_reply_is_bound_to_original_thread(assistant: Gideon) -> None:
    assistant.gmail.get_metadata = Mock(  # type: ignore[method-assign]
        return_value={"from": "Alice <alice@example.com>", "subject": "Plan", "thread_id": "thread-1"}
    )
    assistant.gmail.send = Mock(return_value="message-2")  # type: ignore[method-assign]
    pending = assistant.handle("reply to email abc123 saying approved")
    assert pending.needs_confirmation
    assistant.gmail.send.assert_not_called()
    assistant.handle("confirm")
    assistant.gmail.send.assert_called_once_with(
        "alice@example.com", "Re: Plan", "approved", "personal", "thread-1"
    )


def test_calendar_is_not_created_without_confirmation(assistant: Gideon) -> None:
    assistant.calendar.create = Mock(return_value="event-1")  # type: ignore[method-assign]
    pending = assistant.handle("create event lunch tomorrow at 1 pm")
    assert pending.needs_confirmation
    assistant.calendar.create.assert_not_called()
    assert "created" in assistant.handle("confirm").text
    assistant.calendar.create.assert_called_once()


def test_briefing_degrades_without_credentials(assistant: Gideon) -> None:
    assistant.web.weather = Mock(return_value="Sunny")  # type: ignore[method-assign]
    response = assistant.handle("good morning")
    assert "briefing" in response.text
    assert "Calendar is not configured" in response.text
    assert "Sunny" in response.text


def test_conversion(assistant: Gideon) -> None:
    assert "6.214" in assistant.handle("convert 10 km to miles").text


def test_note_edit_requires_confirmation(assistant: Gideon, database: Database) -> None:
    item_id = database.add_note("Old", "old body")
    pending = assistant.handle(f"edit note {item_id} to New: new body")
    assert pending.needs_confirmation
    assert database.search_notes()[0]["title"] == "Old"
    assistant.handle("confirm")
    assert database.search_notes()[0]["title"] == "New"

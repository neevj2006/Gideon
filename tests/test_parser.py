from datetime import datetime

import pytest

from gideon.parser import CommandParser, parse_time, safe_calculate


@pytest.mark.parametrize(
    ("command", "intent"),
    [
        ("Gideon, add a task buy milk", "todo_add"),
        ("add a task submit report due tomorrow at 5 pm high priority", "todo_add"),
        ("list my tasks", "todo_list"),
        ("remind me to stretch in 5 minutes", "reminder_add"),
        ("start a timer for 20 seconds", "timer_start"),
        ("create note Project: ship v1", "note_add"),
        ("edit note abc123 to Project: ship v2", "note_edit"),
        ("remember that my coffee is black", "memory_remember"),
        ("what do you remember about coffee", "memory_search"),
        ("important unread email in work", "email_read"),
        ("read email 18abc123", "email_message"),
        ("reply to email 18abc123 saying sounds good", "email_reply"),
        ("send email to a@example.com subject Hi body Hello", "email_send"),
        ("tomorrow schedule", "calendar_list"),
        ("find conflicts in my calendar", "calendar_conflicts"),
        ("create event lunch tomorrow at 1 pm", "calendar_create"),
        ("play Daft Punk", "spotify_play"),
        ("current track", "spotify_control"),
        ("weather in Boston", "web_search"),
        ("open calculator", "windows_open"),
        ("take a photo with front camera", "phone"),
        ("summarize clipboard", "clipboard"),
    ],
)
def test_deterministic_intents(command: str, intent: str) -> None:
    result = CommandParser().parse(command)
    assert result is not None
    assert result.name == intent


def test_calculator_is_safe() -> None:
    assert safe_calculate("2 + 3 * 4") == 14
    with pytest.raises(ValueError):
        safe_calculate("__import__('os').system('whoami')")
    with pytest.raises(ValueError):
        safe_calculate("2 ** 100")


def test_relative_time() -> None:
    now = datetime(2026, 1, 1, 10, 0).astimezone()
    assert parse_time("in 15 minutes", now) == now.replace(minute=15)


def test_todo_deadline_and_priority() -> None:
    result = CommandParser().parse("add task submit report due tomorrow at 5 pm high priority")
    assert result is not None
    assert result.args["title"] == "submit report"
    assert result.args["priority"] == 1
    assert result.args["due_at"] is not None

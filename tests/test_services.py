from datetime import datetime, timedelta
from unittest.mock import Mock

from gideon.config import Config
from gideon.db import Database
from gideon.integrations.google import CalendarService, GmailService
from gideon.integrations.spotify import SpotifyService
from gideon.integrations.system import WindowsService
from gideon.scheduler import Scheduler
from tests.conftest import FakeSecrets


def test_gmail_search_maps_headers() -> None:
    api = Mock()
    api.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}]
    }
    api.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Please send the report",
        "labelIds": ["UNREAD"],
        "payload": {
            "headers": [{"name": "From", "value": "a@example.com"}, {"name": "Subject", "value": "Report"}]
        },
    }
    gmail = GmailService(Config())
    gmail._service = Mock(return_value=api)  # type: ignore[method-assign]
    result = gmail.search("is:unread", "work")
    assert result[0]["subject"] == "Report"
    api.users.return_value.messages.return_value.list.assert_called_once()


def test_gmail_send_encodes_message() -> None:
    api = Mock()
    api.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "sent1"}
    gmail = GmailService(Config())
    gmail._service = Mock(return_value=api)  # type: ignore[method-assign]
    assert gmail.send("a@example.com", "Hello", "Body", thread_id="thread") == "sent1"
    payload = api.users.return_value.messages.return_value.send.call_args.kwargs["body"]
    assert payload["threadId"] == "thread" and payload["raw"]


def test_calendar_free_slots() -> None:
    calendar = CalendarService(Config())
    start = datetime(2026, 1, 1, 9).astimezone()
    end = start + timedelta(hours=3)
    calendar.events = Mock(  # type: ignore[method-assign]
        return_value=[
            {
                "start": (start + timedelta(hours=1)).isoformat(),
                "end": (start + timedelta(hours=2)).isoformat(),
            }
        ]
    )
    slots = calendar.free_slots(start, end)
    assert slots == [(start, start + timedelta(hours=1)), (start + timedelta(hours=2), end)]


def test_spotify_controls_mock_client() -> None:
    service = SpotifyService(Config(), FakeSecrets())  # type: ignore[arg-type]
    service._request = Mock(return_value={})  # type: ignore[method-assign]
    service.launch = Mock()  # type: ignore[method-assign]
    assert service.control("pause") == "Paused."
    service._request.assert_called_with("PUT", "/me/player/pause")
    assert service.control("spotify volume 25") == "Spotify volume is 25 percent."
    service._request.assert_called_with("PUT", "/me/player/volume", params={"volume_percent": 25})


def test_windows_open_is_allowlisted() -> None:
    service = WindowsService(Config(approved_apps={"calculator": "calc.exe"}))
    assert "not in the approved" in service.open_app("powershell")


def test_scheduler_timer_cancel(database: Database) -> None:
    scheduler = Scheduler(database)
    scheduler.start_timer(100, "test")
    assert scheduler.cancel_timers() == 1

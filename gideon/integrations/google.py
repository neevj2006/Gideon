from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from ..config import Config, Secrets

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleIntegrationError(RuntimeError):
    pass


class GoogleAuth:
    def __init__(self, cfg: Config, secrets: Secrets | None = None):
        self.cfg = cfg
        self.secrets = secrets or Secrets()

    def credentials(self, alias: str, service: str, interactive: bool = False):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleIntegrationError("Install the google optional dependencies") from exc
        scopes = GMAIL_SCOPES if service == "gmail" else CALENDAR_SCOPES
        secret_name = f"google:{service}:{alias}"
        saved = self.secrets.get(secret_name)
        credentials = Credentials.from_authorized_user_info(json.loads(saved), scopes) if saved else None
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.secrets.set(secret_name, credentials.to_json())
        if credentials and credentials.valid:
            return credentials
        if not interactive:
            raise GoogleIntegrationError(f"Google {service} account '{alias}' needs setup")
        client_file = (
            self.cfg.gmail_accounts.get(alias)
            if service == "gmail"
            else self.cfg.calendar_accounts.get(alias)
        )
        if not client_file or not Path(client_file).exists():
            raise GoogleIntegrationError(
                f"Set {service} OAuth client JSON path for alias '{alias}' in config"
            )
        credentials = InstalledAppFlow.from_client_secrets_file(client_file, scopes).run_local_server(port=0)
        self.secrets.set(secret_name, credentials.to_json())
        return credentials


class GmailService:
    def __init__(self, cfg: Config):
        self.cfg, self.auth = cfg, GoogleAuth(cfg)

    def _service(self, alias: str, interactive: bool = False):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleIntegrationError("Install Gideon with the google optional dependencies") from exc
        return build(
            "gmail",
            "v1",
            credentials=self.auth.credentials(alias, "gmail", interactive),
            cache_discovery=False,
        )

    def search(self, query: str, alias: str = "personal", limit: int = 10) -> list[dict[str, Any]]:
        service = self._service(alias)
        found = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
            .get("messages", [])
        )
        output = []
        for ref in found:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            headers = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
            output.append(
                {
                    "id": msg["id"],
                    "thread_id": msg["threadId"],
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "labels": msg.get("labelIds", []),
                }
            )
        return output

    def get_body(self, message_id: str, alias: str = "personal") -> str:
        message = (
            self._service(alias).users().messages().get(userId="me", id=message_id, format="full").execute()
        )

        def walk(part: dict[str, Any]) -> str:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"] + "===").decode(errors="replace")
            return "\n".join(filter(None, (walk(p) for p in part.get("parts", []))))

        return walk(message.get("payload", {}))

    def get_metadata(self, message_id: str, alias: str = "personal") -> dict[str, Any]:
        message = (
            self._service(alias)
            .users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        headers = {
            item["name"].lower(): item["value"] for item in message.get("payload", {}).get("headers", [])
        }
        return {
            "id": message["id"],
            "thread_id": message["threadId"],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", "(no subject)"),
        }

    def send(
        self, to: str, subject: str, body: str, alias: str = "personal", thread_id: str | None = None
    ) -> str:
        message = EmailMessage()
        message["To"], message["Subject"] = to, subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        payload: dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        sent = self._service(alias).users().messages().send(userId="me", body=payload).execute()
        return str(sent["id"])


class CalendarService:
    def __init__(self, cfg: Config):
        self.cfg, self.auth = cfg, GoogleAuth(cfg)

    def _service(self, alias: str, interactive: bool = False):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleIntegrationError("Install Gideon with the google optional dependencies") from exc
        return build(
            "calendar",
            "v3",
            credentials=self.auth.credentials(alias, "calendar", interactive),
            cache_discovery=False,
        )

    def events(
        self, start: datetime, end: datetime, alias: str = "personal", query: str | None = None
    ) -> list[dict[str, Any]]:
        result = (
            self._service(alias)
            .events()
            .list(
                calendarId="primary",
                timeMin=start.astimezone(UTC).isoformat(),
                timeMax=end.astimezone(UTC).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                q=query,
            )
            .execute()
        )
        return [
            {
                "id": e["id"],
                "summary": e.get("summary", "(untitled)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
                "location": e.get("location", ""),
            }
            for e in result.get("items", [])
        ]

    def conflicts(self, start: datetime, end: datetime, alias: str = "personal") -> list[dict[str, Any]]:
        return self.events(start, end, alias)

    def free_slots(
        self, start: datetime, end: datetime, minutes: int = 30, alias: str = "personal"
    ) -> list[tuple[datetime, datetime]]:
        events = self.events(start, end, alias)
        cursor, slots = start, []
        for event in events:
            event_start = datetime.fromisoformat(event["start"])
            if event_start - cursor >= timedelta(minutes=minutes):
                slots.append((cursor, event_start))
            cursor = max(cursor, datetime.fromisoformat(event["end"]))
        if end - cursor >= timedelta(minutes=minutes):
            slots.append((cursor, end))
        return slots

    def create(self, event: dict[str, Any], alias: str = "personal") -> str:
        return str(self._service(alias).events().insert(calendarId="primary", body=event).execute()["id"])

    def update(self, event_id: str, event: dict[str, Any], alias: str = "personal") -> str:
        return str(
            self._service(alias)
            .events()
            .patch(calendarId="primary", eventId=event_id, body=event)
            .execute()["id"]
        )

    def delete(self, event_id: str, alias: str = "personal") -> None:
        self._service(alias).events().delete(calendarId="primary", eventId=event_id).execute()

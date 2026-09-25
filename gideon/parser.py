from __future__ import annotations

import ast
import operator
import re
from datetime import datetime, timedelta
from typing import Callable

from dateutil import parser as date_parser

from .models import Intent

OPS: dict[type[ast.AST], Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_calculate(expression: str) -> float:
    expression = expression.replace("×", "*").replace("÷", "/").replace("^", "**")
    if len(expression) > 100:
        raise ValueError("expression too long")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent too large")
            return OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](visit(node.operand))
        raise ValueError("unsupported expression")

    return visit(ast.parse(expression, mode="eval"))


def parse_time(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now().astimezone()
    if match := re.search(r"\bin\s+(\d+)\s*(seconds?|minutes?|hours?|days?)\b", text, re.I):
        n, unit = int(match.group(1)), match.group(2).lower()
        return now + timedelta(**{unit.rstrip("s") + "s": n})
    base = now
    lower = text.lower()
    if "tomorrow" in lower:
        base += timedelta(days=1)
    try:
        return date_parser.parse(text, fuzzy=True, default=base)
    except (ValueError, OverflowError):
        return None


class CommandParser:
    def parse(self, raw: str) -> Intent | None:
        text = raw.strip()
        lower = text.lower().strip(" .?!")
        lower = re.sub(r"^gideon[, ]+", "", lower)
        if re.match(r"^(?:yes )?confirm(?: [a-f0-9]{8})?$", lower) or lower == "do it":
            token = lower.rsplit(" ", 1)[-1] if re.search(r"[a-f0-9]{8}$", lower) else None
            return Intent("confirm", {"token": token})
        if lower in {"no", "cancel that", "never mind", "nevermind"}:
            return Intent("cancel_confirmation")
        if lower in {"stop", "stop talking", "quiet", "be quiet"}:
            return Intent("stop_speech")
        if lower in {"quit", "exit", "goodbye"}:
            return Intent("exit")
        if lower in {"help", "what can you do"}:
            return Intent("help")
        if lower.startswith("remember that "):
            fact = text[len(text) - len(lower) + len("remember that ") :].strip()
            topic, value = fact.split(" is ", 1) if " is " in fact.lower() else (fact[:60], fact)
            return Intent("memory_remember", {"topic": topic, "value": value})
        if lower.startswith("what do you remember"):
            query = re.sub(r"^what do you remember(?: about)?\s*", "", lower)
            return Intent("memory_search", {"query": query})
        if lower.startswith("forget that ") or lower.startswith("forget "):
            return Intent("memory_forget", {"query": re.sub(r"^forget(?: that)?\s+", "", lower)}, True)
        if lower.startswith("change that preference"):
            rest = re.sub(r"^change that preference(?: to)?\s*", "", lower)
            topic, _, value = rest.partition(" to ")
            return Intent("memory_remember", {"topic": topic or "preference", "value": value or rest})
        if re.match(r"^(add|create) (?:a )?(?:todo|task)\b", lower):
            title = re.sub(r"^(add|create) (?:a )?(?:todo|task)(?: to)?\s*", "", text, flags=re.I)
            priority = 1 if "high priority" in lower else 3 if "low priority" in lower else 2
            due = parse_time(title) if re.search(r"\b(?:due|by)\b", title, re.I) else None
            clean_title = re.sub(r"\s+(?:due|by)\s+.+$", "", title, flags=re.I)
            clean_title = re.sub(r"\s+(?:high|low|medium) priority\b", "", clean_title, flags=re.I)
            return Intent(
                "todo_add",
                {
                    "title": clean_title.strip(),
                    "priority": priority,
                    "due_at": due.isoformat() if due else None,
                },
            )
        if re.match(r"^(list|show|read)(?: my)? (?:todos|tasks)\b", lower):
            return Intent("todo_list")
        if match := re.match(r"^(?:complete|finish|done) (?:task )?([a-f0-9]{4,8})", lower):
            return Intent("todo_complete", {"id": match.group(1)})
        if match := re.match(r"^(?:delete|remove) (?:task|todo) ([a-f0-9]{4,8})", lower):
            return Intent("todo_delete", {"id": match.group(1)}, True)
        if match := re.match(r"^(?:edit|update) (?:task|todo) ([a-f0-9]{4,8}) (?:to )?(.+)", lower):
            changes = match.group(2)
            edit_priority = 1 if "high priority" in changes else 3 if "low priority" in changes else None
            due = parse_time(changes) if re.search(r"\b(?:due|by)\b", changes) else None
            return Intent(
                "todo_edit",
                {
                    "id": match.group(1),
                    "title": None if edit_priority or due else changes,
                    "priority": edit_priority,
                    "due_at": due.isoformat() if due else None,
                },
            )
        if lower.startswith(("remind me ", "set a reminder ")):
            due = parse_time(lower)
            body = re.sub(r"^(remind me|set a reminder)(?: to)?\s+", "", text, flags=re.I)
            body = re.sub(r"\s+(?:in|at|on)\s+.+$", "", body, flags=re.I)
            recurrence = next((x for x in ("daily", "weekly", "monthly") if x in lower), None)
            return Intent(
                "reminder_add",
                {"text": body, "due_at": due.isoformat() if due else None, "recurrence": recurrence},
            )
        if lower in {"list reminders", "show reminders", "my reminders"}:
            return Intent("reminder_list")
        if match := re.match(r"^(?:delete|cancel) reminder ([a-f0-9]{4,8})", lower):
            return Intent("reminder_delete", {"id": match.group(1)}, True)
        if match := re.match(
            r"^(?:set|start) (?:a )?timer (?:for )?(\d+)\s*(seconds?|minutes?|hours?)", lower
        ):
            return Intent("timer_start", {"amount": int(match.group(1)), "unit": match.group(2)})
        if lower in {"cancel timer", "stop timer", "cancel timers"}:
            return Intent("timer_cancel")
        if lower.startswith(("create note ", "take a note ", "note that ")):
            body = re.sub(r"^(create note|take a note|note that)\s+", "", text, flags=re.I)
            title, sep, content = body.partition(":")
            return Intent("note_add", {"title": title[:80], "body": content.strip() if sep else body})
        if lower.startswith(("search notes", "find note")):
            return Intent(
                "note_search", {"query": re.sub(r"^(search notes|find note)(?: for)?\s*", "", lower)}
            )
        if lower in {"list notes", "show notes", "my notes"}:
            return Intent("note_search", {"query": ""})
        if match := re.match(r"^(?:edit|update) note ([a-f0-9]{4,8}) (?:to )?(.+)", text, re.I):
            body = match.group(2)
            title, separator, content = body.partition(":")
            return Intent(
                "note_edit",
                {
                    "id": match.group(1),
                    "title": title.strip() if separator else None,
                    "body": content.strip() if separator else body,
                },
                True,
            )
        if match := re.match(r"^(?:delete|remove) note ([a-f0-9]{4,8})", lower):
            return Intent("note_delete", {"id": match.group(1)}, True)
        if lower.startswith(("summarize clipboard", "explain clipboard", "rewrite clipboard")):
            return Intent("clipboard", {"operation": lower.split()[0]})
        if match := re.match(r"^(?:calculate|compute|what is)\s+([\d\s.+*/()%^-]+)$", lower):
            return Intent("calculate", {"expression": match.group(1).strip()})
        if lower.startswith(("convert ", "how many ")):
            return Intent("convert", {"query": lower})
        if lower in {"good morning", "morning briefing"}:
            return Intent("briefing", {"period": "today"})
        if lower in {"good night", "tomorrow briefing"}:
            return Intent("briefing", {"period": "tomorrow"})
        if re.search(r"\b(today|tomorrow|week)(?:'s)? (?:calendar|schedule)\b", lower) or lower in {
            "what's on my calendar",
            "calendar",
        }:
            period = "tomorrow" if "tomorrow" in lower else "week" if "week" in lower else "today"
            return Intent("calendar_list", {"period": period, "alias": self._alias(lower)})
        if lower.startswith("find free time"):
            return Intent("calendar_free", {"period": "week", "alias": self._alias(lower)})
        if "calendar conflicts" in lower or "conflicts in my calendar" in lower:
            return Intent("calendar_conflicts", {"period": "week", "alias": self._alias(lower)})
        if lower.startswith("search calendar"):
            return Intent(
                "calendar_search",
                {"query": re.sub(r"^search calendar(?: for)?\s*", "", lower), "alias": self._alias(lower)},
            )
        if re.match(r"^(create|add|schedule) (?:a )?(?:calendar )?event\b", lower):
            return Intent("calendar_create", {"text": text, "alias": self._alias(lower)}, True)
        if match := re.match(r"^(?:update|edit) (?:calendar )?event ([^ ]+)\s+(.+)", lower):
            return Intent(
                "calendar_update",
                {"id": match.group(1), "text": match.group(2), "alias": self._alias(lower)},
                True,
            )
        if match := re.match(r"^(?:delete|cancel) (?:calendar )?event\s+(.+)", lower):
            return Intent("calendar_delete", {"event": match.group(1), "alias": self._alias(lower)}, True)
        if any(x in lower for x in ("email", "inbox", "messages")):
            alias = self._alias(lower)
            if match := re.match(r"^(?:read|open|summarize) email ([a-zA-Z0-9_-]+)", lower):
                return Intent(
                    "email_message",
                    {"id": match.group(1), "alias": alias, "summarize": lower.startswith("summarize")},
                )
            if match := re.match(r"^(?:send )?reply to email ([a-zA-Z0-9_-]+)(?: saying)?\s+(.+)", lower):
                return Intent(
                    "email_reply",
                    {"id": match.group(1), "body": match.group(2), "alias": alias},
                    True,
                )
            if lower.startswith(("send email", "email ")):
                return Intent("email_send", {"text": text, "alias": alias}, True)
            if "draft" in lower or "reply" in lower:
                return Intent("email_draft", {"text": text, "alias": alias})
            return Intent(
                "email_read",
                {
                    "query": self._email_query(lower),
                    "alias": alias,
                    "summarize": "summar" in lower or "action item" in lower,
                },
            )
        if lower.startswith("play "):
            return Intent("spotify_play", {"query": text[5:].strip()})
        if lower in {
            "pause",
            "pause spotify",
            "pause music",
            "resume",
            "resume spotify",
            "next",
            "next song",
            "previous",
            "previous song",
            "current track",
            "what is playing",
            "liked songs",
        }:
            return Intent("spotify_control", {"action": lower})
        if lower.startswith(("shuffle", "repeat", "spotify volume")):
            return Intent("spotify_control", {"action": lower})
        if lower.startswith("open "):
            return Intent("windows_open", {"app": lower[5:].strip()})
        if lower in {
            "mute",
            "unmute",
            "volume up",
            "volume down",
            "battery",
            "battery status",
            "lock pc",
            "lock computer",
        }:
            return Intent("windows_control", {"action": lower})
        phone_words = ("phone", "flashlight", "front camera", "back camera", "silent video", "alarm")
        if any(word in lower for word in phone_words):
            return Intent("phone", {"command": lower})
        if lower.startswith(("search web", "search for", "look up", "weather", "news", "current events")):
            return Intent(
                "web_search", {"query": re.sub(r"^(search web|search for|look up)\s*", "", text, flags=re.I)}
            )
        return None

    @staticmethod
    def _alias(text: str) -> str:
        match = re.search(r"\b(?:my|from|in|on) (personal|bu|work)\b", text)
        return match.group(1) if match else "personal"

    @staticmethod
    def _email_query(text: str) -> str:
        parts = []
        if "unread" in text:
            parts.append("is:unread")
        if "important" in text:
            parts.append("is:important")
        if match := re.search(r"(?:from|about|search(?: email)? for)\s+(.+)", text):
            parts.append(match.group(1))
        return " ".join(parts) or "in:inbox"

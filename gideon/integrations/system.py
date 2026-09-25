from __future__ import annotations

import ctypes
import subprocess
import webbrowser

import psutil

from ..config import Config


class WindowsService:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def open_app(self, name: str) -> str:
        executable = self.cfg.approved_apps.get(name.lower())
        if not executable:
            return f"{name} is not in the approved application list."
        try:
            subprocess.Popen([executable], creationflags=0x08000000)
            return f"Opening {name}."
        except OSError as exc:
            return f"I could not open {name}: {exc}."

    def control(self, action: str) -> str:
        if "battery" in action:
            battery = psutil.sensors_battery()
            if not battery:
                return "Battery information is unavailable."
            charging = "charging" if battery.power_plugged else "on battery"
            return f"Battery is at {round(battery.percent)} percent and {charging}."
        if "lock" in action:
            ctypes.windll.user32.LockWorkStation()
            return "Locking the computer."
        key = 0xAD if action in {"mute", "unmute"} else 0xAF if "up" in action else 0xAE
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        return "Volume updated."


def clipboard_text() -> str:
    """Return the current clipboard text."""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return str(root.clipboard_get())
        finally:
            root.destroy()
    except Exception as exc:
        raise RuntimeError("Clipboard does not contain readable text") from exc


def open_approved_url(url: str) -> None:
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError("Only HTTP(S) URLs are allowed")
    webbrowser.open(url)


def notify(title: str, message: str) -> None:
    try:
        from winotify import Notification

        Notification(app_id="Gideon", title=title, msg=message).show()
    except Exception:
        try:
            ctypes.windll.user32.MessageBeep(0x40)
        except Exception:
            pass

from __future__ import annotations

import logging
import threading
import time

from .assistant import Gideon
from .audio import Listener, Speaker
from .config import LOG_PATH, PID_PATH, STOP_PATH


def run_daemon() -> None:
    import os

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    STOP_PATH.unlink(missing_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    assistant, speaker = Gideon(), Speaker()
    listener = Listener(assistant.cfg)
    stop_monitor = threading.Event()

    def monitor_stop() -> None:
        while not STOP_PATH.exists():
            time.sleep(0.25)
        stop_monitor.set()

    threading.Thread(target=monitor_stop, daemon=True).start()
    scheduler_thread = threading.Thread(target=assistant.scheduler.run, daemon=True)
    scheduler_thread.start()
    logging.info("Gideon daemon started")
    try:
        while not STOP_PATH.exists():
            phrase = listener.wait_for_wake_word(stop_monitor)
            if not phrase:
                continue
            command = phrase.lower().split(assistant.cfg.wake_word, 1)[1].strip(" ,")
            if not command:
                speaker.speak("Yes?")
                try:
                    command = listener.listen(timeout=assistant.cfg.followup_seconds)
                except Exception:
                    continue
            followup_until = time.monotonic() + assistant.cfg.followup_seconds
            while command and not STOP_PATH.exists():
                reply = assistant.handle(command)
                if reply.data and reply.data.get("stop_speech"):
                    speaker.stop()
                elif reply.speak:
                    speaker.speak_async(reply.text)
                if reply.data and reply.data.get("exit"):
                    break
                if time.monotonic() >= followup_until:
                    break
                try:
                    command = listener.listen(timeout=max(1, followup_until - time.monotonic()))
                except Exception:
                    break
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("Daemon crashed")
    finally:
        assistant.scheduler.stop()
        speaker.stop()
        PID_PATH.unlink(missing_ok=True)
        STOP_PATH.unlink(missing_ok=True)
        logging.info("Gideon daemon stopped")

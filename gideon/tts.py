from __future__ import annotations

import base64
import sys


def main() -> None:
    import pyttsx3

    text = base64.urlsafe_b64decode(sys.argv[1]).decode()
    engine = pyttsx3.init()
    engine.setProperty("rate", 180)
    engine.say(text)
    engine.runAndWait()


if __name__ == "__main__":
    main()

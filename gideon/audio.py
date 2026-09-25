from __future__ import annotations

import audioop
import base64
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import Config


class Speaker:
    """Run speech in a subprocess so playback can be interrupted."""

    def __init__(self):
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None

    def speak(self, text: str) -> None:
        with self._lock:
            encoded = base64.urlsafe_b64encode(text.encode()).decode()
            flags = 0x08000000 if sys.platform == "win32" else 0
            self._process = subprocess.Popen(
                [sys.executable, "-m", "gideon.tts", encoded], creationflags=flags
            )
            process = self._process
        process.wait()
        with self._lock:
            if self._process is process:
                self._process = None

    def speak_async(self, text: str) -> None:
        threading.Thread(target=self.speak, args=(text,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()


class Listener:
    """SoundDevice capture with offline Vosk or optional online Google STT."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._vosk_model = None

    def listen(self, timeout: float | None = None, phrase_limit: float = 12) -> str:
        import sounddevice as sd
        import speech_recognition as sr

        sample_rate, block_ms = 16000, 100
        blocksize = sample_rate * block_ms // 1000
        chunks: list[bytes] = []
        started_at, last_speech = time.monotonic(), None
        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=blocksize, dtype="int16", channels=1
        ) as stream:
            while time.monotonic() - started_at < (timeout or 3600):
                data, _ = stream.read(blocksize)
                raw = bytes(data)
                if audioop.rms(raw, 2) > 350:
                    last_speech = time.monotonic()
                if last_speech is not None:
                    chunks.append(raw)
                    elapsed = len(chunks) * block_ms / 1000
                    if time.monotonic() - last_speech > 0.8 or elapsed >= phrase_limit:
                        break
        if not chunks:
            raise TimeoutError("No speech detected")
        audio = sr.AudioData(b"".join(chunks), sample_rate, 2)
        recognizer = sr.Recognizer()
        if self.cfg.vosk_model_path and Path(self.cfg.vosk_model_path).exists():
            from vosk import KaldiRecognizer, Model

            if self._vosk_model is None:
                self._vosk_model = Model(self.cfg.vosk_model_path)
            offline = KaldiRecognizer(self._vosk_model, sample_rate)
            offline.AcceptWaveform(audio.get_raw_data())
            return str(json.loads(offline.FinalResult()).get("text", ""))
        return str(recognizer.recognize_google(audio))

    def wait_for_wake_word(self, stop_event: threading.Event | None = None) -> str:
        while not (stop_event and stop_event.is_set()):
            try:
                phrase = self.listen(timeout=2, phrase_limit=5)
                if self.cfg.wake_word.lower() in phrase.lower():
                    return phrase
            except Exception:
                continue
        return ""

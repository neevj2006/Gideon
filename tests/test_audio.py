from unittest.mock import Mock, patch

from gideon.audio import Speaker


def test_speech_can_be_interrupted() -> None:
    process = Mock()
    process.poll.return_value = None
    with patch("subprocess.Popen", return_value=process):
        speaker = Speaker()
        speaker._process = process
        speaker.stop()
    process.terminate.assert_called_once()

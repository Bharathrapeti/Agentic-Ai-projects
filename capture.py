"""Optional browser capture and speech helpers.

Every integration is optional so the typed-answer flow works even when browser
permissions, native codecs, or network speech services are unavailable.
"""

from __future__ import annotations

import io
import base64
import binascii


def available() -> tuple[bool, str]:
    try:
        import streamlit_mic_recorder  # noqa: F401
        return True, "Audio recording component available."
    except ImportError:
        return False, "Optional audio capture is not installed; typed answers remain available."


def audio_input(key: str):
    try:
        from streamlit_mic_recorder import mic_recorder
        return mic_recorder(start_prompt="Record answer", stop_prompt="Stop recording", key=key)
    except ImportError:
        return None


def live_stream(key: str, audio: bool = True):
    """Render a WebRTC camera/microphone stream when streamlit-webrtc is installed."""
    try:
        from streamlit_webrtc import WebRtcMode, webrtc_streamer

        return webrtc_streamer(
            key=key,
            mode=WebRtcMode.SENDRECV,
            media_stream_constraints={"video": True, "audio": audio},
            async_processing=True,
        )
    except ImportError:
        return None


def transcribe_audio(audio_bytes: bytes, language: str = "en-IN") -> tuple[str | None, str | None]:
    """Transcribe WAV/AIFF/FLAC bytes with SpeechRecognition.

    Returns ``(text, error)`` rather than raising so the UI can always offer
    typed input as a fallback.
    """
    if not audio_bytes:
        return None, "No audio was recorded."
    try:
        import speech_recognition as sr
    except ImportError:
        return None, "Speech-to-text is not installed; type your answer instead."
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language=language), None
    except sr.UnknownValueError:
        return None, "Speech was not clear enough to transcribe; type your answer instead."
    except sr.RequestError:
        return None, "Speech service is unavailable; type your answer instead."
    except (ValueError, OSError):
        return None, "Audio format could not be read; type your answer instead."


def transcribe_base64_wav(encoded_audio: str, language: str = "en-IN") -> tuple[str | None, str | None]:
    try:
        return transcribe_audio(base64.b64decode(encoded_audio), language)
    except (ValueError, binascii.Error):
        return None, "The recorded audio was invalid; type your answer instead."


def question_audio(text: str) -> bytes | None:
    """Create browser-playable MP3 speech with gTTS when available."""
    try:
        from gtts import gTTS

        output = io.BytesIO()
        gTTS(text=text, lang="en").write_to_fp(output)
        return output.getvalue()
    except Exception:
        return None

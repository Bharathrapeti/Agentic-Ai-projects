"""Optional browser capture and speech helpers.

Every integration is optional so the typed-answer flow works even when browser
permissions, native codecs, or network speech services are unavailable.
"""

from __future__ import annotations

import io
import base64
import binascii
import logging
from functools import lru_cache
from pathlib import Path

import streamlit.components.v1 as components


logger = logging.getLogger(__name__)

_camera_precheck_component = components.declare_component(
    "camera_precheck_v2",
    path=str(Path(__file__).parent / "frontend" / "camera_precheck"),
)


@lru_cache(maxsize=1)
def available() -> tuple[bool, str]:
    try:
        import streamlit_mic_recorder  # noqa: F401
        return True, "Audio recording component available."
    except ImportError:
        return False, "Optional audio capture is not installed; typed answers remain available."


def audio_input(
    key: str,
    start_prompt: str = "Record answer",
    stop_prompt: str = "Stop recording",
    audio_format: str = "wav",
):
    try:
        from streamlit_mic_recorder import mic_recorder
        return mic_recorder(
            start_prompt=start_prompt,
            stop_prompt=stop_prompt,
            format=audio_format,
            key=key,
        )
    except ImportError:
        return None


def live_stream(
    key: str,
    audio: bool = True,
    mirror_preview: bool = False,
    auto_start: bool = False,
):
    """Render a WebRTC camera/microphone stream when streamlit-webrtc is installed."""
    try:
        from streamlit_webrtc import WebRtcMode, webrtc_streamer

        video_html_attrs = (
            {
                "autoPlay": True,
                "playsInline": True,
                "muted": True,
                "style": {
                    "width": "100%",
                    "height": "360px",
                    "maxHeight": "none",
                    "aspectRatio": "16 / 9",
                    "objectFit": "contain",
                    "transform": "scaleX(-1)",
                },
            }
            if mirror_preview
            else None
        )
        return webrtc_streamer(
            key=key,
            mode=WebRtcMode.SENDRECV,
            media_stream_constraints={"video": True, "audio": audio},
            async_processing=True,
            video_html_attrs=video_html_attrs,
            desired_playing_state=True if auto_start else None,
        )
    except ImportError:
        return None


def camera_precheck(
    key: str = "camera_precheck",
    start_request: int = 0,
    stop_request: int = 0,
) -> dict:
    """Render the browser-owned pre-check camera and return its verified state."""
    return _camera_precheck_component(
        key=key,
        start_request=start_request,
        stop_request=stop_request,
        default={},
    )


def transcribe_audio(audio_bytes: bytes, language: str = "en-IN") -> tuple[str | None, str | None]:
    """Transcribe WAV/AIFF/FLAC bytes with SpeechRecognition.

    Returns ``(text, error)`` rather than raising so the UI can always offer
    typed input as a fallback.
    """
    if not audio_bytes:
        return None, "No audio was recorded."
    logger.info(
        "Transcription input: bytes=%d, header=%s",
        len(audio_bytes),
        audio_bytes[:12].hex(),
    )
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
    except (ValueError, OSError) as error:
        logger.exception(
            "Audio decoding failed: bytes=%d, header=%s, error_type=%s",
            len(audio_bytes),
            audio_bytes[:12].hex(),
            type(error).__name__,
        )
        return None, "Audio format could not be read; type your answer instead."


def transcribe_base64_wav(encoded_audio: str, language: str = "en-IN") -> tuple[str | None, str | None]:
    try:
        audio_bytes = base64.b64decode(encoded_audio)
        return transcribe_audio(audio_bytes, language)
    except (ValueError, binascii.Error) as error:
        logger.exception("Base64 audio decoding failed: error_type=%s", type(error).__name__)
        return None, "The recorded audio was invalid; type your answer instead."


@lru_cache(maxsize=128)
def question_audio(text: str) -> bytes | None:
    """Create browser-playable MP3 speech with gTTS when available."""
    try:
        from gtts import gTTS

        output = io.BytesIO()
        gTTS(text=text, lang="en").write_to_fp(output)
        return output.getvalue()
    except Exception:
        return None

"""ElevenLabs voice: dictate a research idea (speech-to-text) and listen to the plain-language
briefing of results (text-to-speech). Optional - requires ELEVENLABS_API_KEY; the browser's
built-in speech recognition is used as a fallback for dictation."""
from __future__ import annotations

import httpx

from .config import settings
from .privacy import scrub

API = "https://api.elevenlabs.io/v1"


class VoiceError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(settings.elevenlabs_key)


def tts(text: str) -> bytes:
    if not enabled():
        raise VoiceError("ELEVENLABS_API_KEY not configured")
    clean, _ = scrub(text[:2500])
    r = httpx.post(f"{API}/text-to-speech/{settings.elevenlabs_voice}", timeout=60,
                   headers={"xi-api-key": settings.elevenlabs_key, "accept": "audio/mpeg", "content-type": "application/json"},
                   json={"text": clean, "model_id": settings.elevenlabs_tts_model})
    if r.status_code >= 400:
        raise VoiceError(f"ElevenLabs TTS {r.status_code}: {r.text[:200]}")
    return r.content


def stt(audio: bytes, filename: str = "idea.webm", content_type: str = "audio/webm") -> str:
    if not enabled():
        raise VoiceError("ELEVENLABS_API_KEY not configured")
    r = httpx.post(f"{API}/speech-to-text", timeout=120, headers={"xi-api-key": settings.elevenlabs_key},
                   data={"model_id": settings.elevenlabs_stt_model}, files={"file": (filename, audio, content_type)})
    if r.status_code >= 400:
        raise VoiceError(f"ElevenLabs STT {r.status_code}: {r.text[:200]}")
    return r.json().get("text", "")

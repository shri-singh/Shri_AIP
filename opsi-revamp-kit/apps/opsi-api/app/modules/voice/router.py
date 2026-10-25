"""Voice endpoints - 404 unless OPSI_VOICE_ENABLED=true and a VoiceService is configured."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from .._shared.container import OpsiServices, services
from .._shared.errors import BadRequest, NotFound
from ..identity.deps import require
from ..identity.principal import Principal
from .service import MAX_AUDIO_BYTES, SynthesizeRequest, TranscribeRequest

router = APIRouter(prefix="/api/v2/voice", tags=["voice"])


def _voice(svc: OpsiServices):
    voice = (svc.extras or {}).get("voice")
    if not svc.settings.voice_enabled or voice is None:
        raise NotFound("voice")
    return voice


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), consent: bool = Form(...), locale: str = Form("en-US"),
                     thread_id: uuid.UUID = Form(...), p: Principal = Depends(require("chat:use")),
                     svc: OpsiServices = Depends(services)) -> dict:
    voice = _voice(svc)
    req = TranscribeRequest(consent=consent, locale=locale, thread_id=thread_id)  # consent must be literally true
    if not await svc.chat.get_thread(p, req.thread_id):
        raise NotFound("thread")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    try:
        transcript = await voice.transcribe_clip(data, audio.content_type or "", req.locale, p.tenant_id)
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    return {"text": transcript.text, "machine_generated": True}


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest, p: Principal = Depends(require("chat:use")),
                     svc: OpsiServices = Depends(services)) -> Response:
    audio = await _voice(svc).synthesize(body)
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

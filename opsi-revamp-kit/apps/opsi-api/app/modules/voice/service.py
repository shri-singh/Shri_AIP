"""Voice adapter (future): push-to-talk STT via Amazon Transcribe, TTS via Amazon Polly.

Disabled unless OPSI_VOICE_ENABLED=true. Design rules (docs/voice-roadmap.md):
- explicit per-session consent; no background capture; text chat always available;
- audio is processed in memory/temporary S3 objects and deleted (no retention by default);
- transcripts become normal *user* chat messages (marked machine-generated) and go through
  the same agent endpoint, so all agent controls apply unchanged;
- no AWS credentials in the browser - the API calls Transcribe/Polly with its instance role.

The batch path (StartTranscriptionJob on a temporary S3 object) is the simplest to
operate first. Streaming STT (Transcribe streaming over HTTP/2/WebSocket) needs the
``amazon-transcribe`` SDK and a WebSocket-capable gateway; evaluate it in phase 5b.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_AUDIO = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3", "audio/mp4": "mp4"}
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # ~60 s of compressed speech
log = logging.getLogger(__name__)


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: Literal[True] = Field(description="Must be true: the user explicitly consented for this recording")
    locale: str = Field(default="en-US", pattern=r"^[a-z]{2}-[A-Z]{2}$")
    thread_id: uuid.UUID


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3000)
    voice_id: str = Field(default="Joanna", pattern=r"^[A-Za-z]{2,20}$")
    engine: Literal["standard", "neural"] = "neural"


@dataclass
class Transcript:
    text: str
    machine_generated: bool = True


class VoiceService:
    def __init__(self, *, bucket: str, region: str, s3: Any = None, transcribe: Any = None, polly: Any = None,
                 sleep: Callable[[float], Any] = asyncio.sleep, poll_seconds: float = 2.0, timeout_s: float = 60) -> None:
        import boto3

        self.bucket = bucket
        self.s3 = s3 or boto3.client("s3", region_name=region)
        self.transcribe = transcribe or boto3.client("transcribe", region_name=region)
        self.polly = polly or boto3.client("polly", region_name=region)
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.timeout_s = timeout_s

    async def transcribe_clip(self, audio: bytes, mime_type: str, locale: str, tenant_id: str) -> Transcript:
        if mime_type not in ALLOWED_AUDIO:
            raise ValueError("unsupported audio type")
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("audio missing or too long")
        job = f"opsi-{uuid.uuid4().hex}"
        key = f"voice-tmp/tenant={tenant_id}/{job}.{ALLOWED_AUDIO[mime_type]}"
        await asyncio.to_thread(self.s3.put_object, Bucket=self.bucket, Key=key, Body=audio, ContentType=mime_type,
                                ServerSideEncryption="aws:kms")
        try:
            await asyncio.to_thread(
                self.transcribe.start_transcription_job, TranscriptionJobName=job, LanguageCode=locale,
                Media={"MediaFileUri": f"s3://{self.bucket}/{key}"}, MediaFormat=ALLOWED_AUDIO[mime_type],
                OutputBucketName=self.bucket, OutputKey=f"voice-tmp/tenant={tenant_id}/{job}.json")
            waited = 0.0
            while True:
                status = await asyncio.to_thread(self.transcribe.get_transcription_job, TranscriptionJobName=job)
                state = status["TranscriptionJob"]["TranscriptionJobStatus"]
                if state == "COMPLETED":
                    break
                if state == "FAILED" or waited > self.timeout_s:
                    raise RuntimeError("transcription failed or timed out")
                await self.sleep(self.poll_seconds)
                waited += self.poll_seconds
            import json

            body = await asyncio.to_thread(self.s3.get_object, Bucket=self.bucket,
                                           Key=f"voice-tmp/tenant={tenant_id}/{job}.json")
            data = json.loads(body["Body"].read())
            text = " ".join(t["transcript"] for t in data["results"]["transcripts"])
            return Transcript(text=text.strip())
        finally:  # no retention: delete audio, transcript JSON and the job record
            for k in (key, f"voice-tmp/tenant={tenant_id}/{job}.json"):
                try:
                    await asyncio.to_thread(self.s3.delete_object, Bucket=self.bucket, Key=k)
                except Exception:  # noqa: BLE001 - lifecycle rule on voice-tmp/ is the backstop
                    log.warning("could not delete temporary voice object; lifecycle rule will expire it")
            try:
                await asyncio.to_thread(self.transcribe.delete_transcription_job, TranscriptionJobName=job)
            except Exception:  # noqa: BLE001
                log.warning("could not delete transcription job %s", job)

    async def synthesize(self, req: SynthesizeRequest) -> bytes:
        response = await asyncio.to_thread(self.polly.synthesize_speech, Text=req.text, VoiceId=req.voice_id,
                                           OutputFormat="mp3", Engine=req.engine)
        return response["AudioStream"].read()

# Future speech / voice capability

Implement voice as an *adapter*, not another model stack:
`React microphone (push-to-talk initially) -> authenticated FastAPI /voice/transcribe -> Amazon Transcribe (STT) -> Opsi agent/AG-UI -> Bedrock via Portkey -> Amazon Polly (TTS) -> React audio player`.

Later: bidirectional streaming with interrupt/barge-in, partial transcripts, optional real-time speech model (evaluate separately), and voice activity detection.

Design contracts:
- `VoiceSession {id, tenant_id, user_id, chat_thread_id, consent, locale, created_at}`
- `TranscribeRequest {audio_object_or_bytes, codec, locale, session_id}`
- `SpeechChunk {sequence, mime_type, payload, transcript_ref}`
- API interface in `backend/opsi_modules/voice.py`.

Controls: explicit permission and consent; no background recording; PII redaction; encrypted temporary audio, minimal retention, no voice credential in React; WebSocket upgrade only under approved gateway; mark machine-generated transcripts; text chat remains available for accessibility. Polly voice quality, locales and pricing require selection.

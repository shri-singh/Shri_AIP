# Voice roadmap

Principle (ADR-0019): voice is an **adapter** in front of the same agent. Text chat remains the universal,
accessible path; voice never gets extra powers.

## Stage A - push-to-talk, batch STT, optional TTS (implemented as stubs, disabled)
```
[mic button, explicit consent per recording] -> MediaRecorder (webm/opus, <= 60 s)
  -> POST /api/v2/voice/transcribe (multipart: audio, consent=true, locale, thread_id)
     -> temp S3 object (SSE-KMS, voice-tmp/, lifecycle 1 day) -> Amazon Transcribe batch job
     -> transcript text -> DELETE audio + transcript + job
  <- {text, machine_generated: true}
  -> user edits/confirms text -> normal chat message through the agent
[optional] answer text -> POST /api/v2/voice/synthesize -> Amazon Polly mp3 (no-store) -> <audio>
```
Enable in lab only: `OPSI_VOICE_ENABLED=true`, IAM statement `VoiceOptionalTranscribePolly`, bucket lifecycle rule
`voice-temp-never-retained`.

Browser notes: `navigator.mediaDevices.getUserMedia({audio: true})` needs HTTPS and a user gesture; show a recording
indicator; stop tracks after recording; provide keyboard access and captions (the transcript itself).

## Stage B - streaming STT and barge-in (evaluate)
- Amazon Transcribe streaming (HTTP/2 or WebSocket; Python `amazon-transcribe` SDK) behind a WebSocket endpoint on the
  API; NGINX `proxy_set_header Upgrade/Connection` for that location only; partial transcripts shown live.
- Barge-in: client stops TTS playback on speech start; server cancels the run (AG-UI `agent/stop` via runtime).
- Latency budget: < 1.5 s to first partial transcript; < 3 s to first answer token.

## Stage C - real-time speech models (separate evaluation)
Only after data-residency, cost and accuracy review; must still route through Opsi authorization and tools.

## Controls checklist
- [ ] Consent captured per recording (UI + `consent=true` field enforced by the API)
- [ ] No background recording; visible indicator; easy cancel
- [ ] No retention by default; lifecycle backstop; no audio in logs/traces
- [ ] PII redaction applied to transcripts before they enter prompts (same redactor)
- [ ] Locale/voice selection reviewed (Polly voices and engines differ by region)
- [ ] Accessibility: text alternative always available; transcripts editable before sending
- [ ] Pricing reviewed (Transcribe per second, Polly per character)

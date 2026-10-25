# ADR-0019: Voice is an adapter over the same agent; text remains the universal path
- Status: Accepted
- Date: 2026-10-24

## Context
Future requirement: push-to-talk, transcription (Amazon Transcribe), spoken answers (Amazon Polly), later streaming
and barge-in. Voice adds consent, retention and accessibility concerns; CopilotKit's runtime also has a
`transcribe` route (blocked by our runtime allowlist because it would bypass our controls).

## Decision
- `apps/opsi-api/app/modules/voice`: `POST /api/v2/voice/transcribe` (explicit `consent=true`, <= 5 MB clip, KMS-encrypted
  temporary S3 object, batch Transcribe job, transcript + audio deleted in `finally`, lifecycle rule as backstop),
  `POST /api/v2/voice/synthesize` (Polly, `Cache-Control: no-store`). 404 unless `OPSI_VOICE_ENABLED=true`.
- The transcript is sent as a normal **user message** through the same agent endpoint (marked machine-generated);
  every agent control applies unchanged. Text chat always available.
- Phase 5b: evaluate streaming STT and real-time speech models separately (latency, cost, data residency).

## Verification
Router returns 404 when disabled (default); consent is a `Literal[True]` field; see [../voice-roadmap.md](../voice-roadmap.md).

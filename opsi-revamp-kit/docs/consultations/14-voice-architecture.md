# 14 - Voice architecture options

## The question
"How should voice work, and what are the trade-offs?"

## Options
| Option | Latency | Complexity | Privacy | Fit |
|---|---|---|---|---|
| A. Push-to-talk + batch Transcribe + optional Polly (kit stub) | 3-10 s | low | audio deleted immediately | first prototype, accessibility |
| B. Streaming Transcribe over WebSocket + streamed text answer + Polly per sentence | ~1-3 s | medium (WebSocket, HTTP/2 SDK, NGINX upgrade) | same controls | conversational use |
| C. Real-time speech-to-speech model | < 1 s | high | depends on provider/region | only after separate evaluation |
| D. Browser-native Web Speech API | low | low | **audio may go to the browser vendor's cloud** | not acceptable for corporate data unless approved |

## Recommended path
A now (lab), B when users ask for hands-free operations, C only with a dedicated review. Every option produces text that
enters the same agent endpoint; no separate tool access for voice.

## Design details for B
- Endpoint `GET /api/v2/voice/stream` (WebSocket) authenticated like REST; NGINX location with `Upgrade` headers.
- Client sends 16 kHz PCM/opus chunks; server streams to Transcribe and emits partial/final transcripts.
- On final transcript the client sends a normal chat run; answer streaming continues via AG-UI; TTS per sentence.
- Barge-in: client detects speech start -> stops audio -> calls runtime `agent/stop`.

## Non-functional
Accessibility (captions = transcripts), locales, noisy environments (push-to-talk), consent per session, explicit
indicator, rate limits, cost per minute.

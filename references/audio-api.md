# Audio API quick reference

- Endpoint: `POST /v1/audio/speech` through the OpenAI Python SDK.
- Default model: `gpt-4o-mini-tts-2025-12-15`.
- Input limit: 4096 characters per request.
- Parameters: `model`, `input`, `voice`, `instructions`, `response_format`, and `speed`.
- Formats: `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm`.
- `instructions` are not supported by `tts-1` or `tts-1-hd`.
- Provide a clear disclosure that the resulting voice is AI-generated when users will hear it.

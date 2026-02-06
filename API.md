# Linguada API

API for YouTube subtitle generation. The service is asynchronous: you enqueue a job, poll status, then fetch subtitles.

Base URL (default): `http://localhost:8000`

## Endpoints

### `GET /`
Health/metadata.

Response `200`
```json
{
  "service": "Linguada Subtitle Generator",
  "version": "2.0.0",
  "status": "running",
  "features": [
    "YouTube subtitle generation",
    "Fast CPU processing",
    "Model caching"
  ]
}
```

### `GET /health`
Simple health check.

Response `200`
```json
{ "status": "healthy", "service": "linguada" }
```

---



### `GET /api/videos`
Fetch list of available videos from the Berios collection. The list is cached in Redis for 10 minutes and served from cache first.

Response `200`
```json
{
  "ok": true,
  "source": "cache",
  "videos": [
    {
      "id": "...",
      "video_id": "...",
      "title": "...",
      "thumbnail_url": "...",
      "duration_sec": 123,
      "uploader": "..."
    }
  ]
}
```

### `POST /api/subtitles`
Enqueue subtitle generation for a YouTube video.

Request body (JSON)
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "video_id": "VIDEO_ID"
}
```
- `url` (required): YouTube URL.
- `video_id` (optional): If omitted, the API will try to extract it from `url`.

Responses
- `200` when subtitles already cached:
```json
{ "ok": true, "video_id": "VIDEO_ID", "status": "done" }
```
- `202` when job is queued or already processing:
```json
{ "ok": true, "video_id": "VIDEO_ID", "status": "processing" }
```
- `400` when `url` is missing or video_id cannot be extracted:
```json
{ "detail": "url is required" }
```
```json
{ "detail": "Could not extract video_id from url" }
```
- `429` when rate limit exceeded:
```json
{ "error": "Rate limit exceeded. Try again later." }
```

Notes
- Rate limit is IP-based for this endpoint.
- Background job status is stored in Redis.

---

### `GET /api/subtitles/{video_id}/status`
Check processing status for a video.

Responses
- `200` when status exists:
```json
{ "ok": true, "video_id": "VIDEO_ID", "status": "processing" }
```
```json
{ "ok": true, "video_id": "VIDEO_ID", "status": "done" }
```
```json
{ "ok": true, "video_id": "VIDEO_ID", "status": "error" }
```
- `200` when nothing found:
```json
{ "ok": false, "video_id": "VIDEO_ID", "status": "not_found" }
```

---

### `GET /api/subtitles/{video_id}`
Fetch generated subtitles.

Responses
- `200` when cached subtitles are ready:
```json
{
  "ok": true,
  "video_id": "VIDEO_ID",
  "subtitles": {
    "text": "Full transcript text...",
    "language": "en",
    "segments": [
      {
        "id": 0,
        "start": 0.0,
        "end": 2.34,
        "text": "Hello world",
        "words": [
          { "word": "Hello", "start": 0.0, "end": 0.8, "confidence": 0.98 },
          { "word": "world", "start": 0.9, "end": 2.34, "confidence": 0.96 }
        ]
      }
    ],
    "meta": {
      "engine": "ultra-fast-whisper",
      "model": "tiny",
      "compute_type": "int8",
      "device": "cpu",
      "num_workers": 4,
      "beam_size": 1,
      "language_hint": "en",
      "vad_filter": true,
      "duration_audio_sec": 120.5,
      "asr_time_sec": 12.3,
      "rtf": 0.102,
      "speedup_factor": 9.8,
      "cache": {
        "cached": true,
        "cache_dir": "/root/.cache/linguada/models",
        "cache_size_mb": 512.3
      }
    }
  }
}
```
- `202` when still processing:
```json
{ "ok": true, "video_id": "VIDEO_ID", "detail": "processing" }
```
- `404` when subtitles not found:
```json
{ "detail": "Subtitles not found" }
```


### `POST /api/subtitles/{video_id}/translation`
Enqueue translation for already generated subtitles.

Request body (JSON)
```json
{
  "target_language": "ru",
  "source_language": "en"
}
```
- `target_language` (optional, default `ru`): target language code.
- `source_language` (optional): source language code. If omitted, it uses the subtitle language.

Responses
- `200` when translation already cached:
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "status": "done" }
```
- `202` when job is queued or already processing:
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "status": "processing" }
```
- `404` when subtitles are missing:
```json
{ "detail": "Subtitles not found" }
```

---

### `GET /api/subtitles/{video_id}/translation/status`
Check translation status for a video.

Query params
- `target_language` (optional, default `ru`)

Responses
- `200` when status exists:
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "status": "processing" }
```
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "status": "done" }
```
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "status": "error" }
```
- `200` when nothing found:
```json
{ "ok": false, "video_id": "VIDEO_ID", "target_language": "ru", "status": "not_found" }
```

---

### `GET /api/subtitles/{video_id}/translation`
Fetch translated subtitles.

Query params
- `target_language` (optional, default `ru`)

Responses
- `200` when cached translation is ready:
```json
{
  "ok": true,
  "video_id": "VIDEO_ID",
  "target_language": "ru",
  "translation": {
    "text": "Полный текст перевода...",
    "language": "ru",
    "segments": [
      { "id": 0, "start": 0.0, "end": 2.34, "text": "Привет мир" }
    ],
    "meta": {
      "engine": "argos-translate",
      "source_language": "en",
      "target_language": "ru",
      "mode": "tagged"
    }
  }
}
```
- `202` when still processing:
```json
{ "ok": true, "video_id": "VIDEO_ID", "target_language": "ru", "detail": "processing" }
```
- `404` when translation not found:
```json
{ "detail": "Translation not found" }
```

---

## Typical frontend flow
1) `POST /api/subtitles` with `url`.
2) Poll `GET /api/subtitles/{video_id}/status` until `status=done`.
3) Fetch result via `GET /api/subtitles/{video_id}`.

## Environment settings that affect API
- `DOWNLOADING_EXPIRE_TIME` (seconds, default 3600): TTL for status/processing keys; cached subtitles are stored for `2x` this time.
- `RATE_LIMIT_MAX_REQUESTS` (default 50): max requests per window for rate limited endpoints.
- `RATE_LIMIT_WINDOW` (default 3600 seconds): rate limit window length.
- `MAX_AUDIO_DURATION` (seconds, default 1800): max allowed video duration.
- `VIDEO_CATALOG_COLLECTION` (default `videos`): MongoDB collection used as the video catalog source for `GET /api/videos`.
- `VIDEO_CATALOG_CACHE_KEY` (default `videos:all`): Redis key for the cached video list.
- `VIDEO_CATALOG_CACHE_TTL_SEC` (default `600`): TTL for video list cache; background refresher runs on this interval.

## Errors
Common errors:
- `400` invalid input.
- `404` subtitles missing.
- `429` rate limit exceeded.
- `500` unexpected server error.

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

### `GET /api/updates/latest`
Fetch the latest active update notice. If a critical update is active, it is returned even if previously seen.

Query params
- `app_version` (optional): client version to compare against `version` / `min_app_version`.
- `device_id` (optional): used to skip info updates that were already acknowledged.
- `user_id` (optional): same as `device_id` but for authenticated clients.

Response `200`
```json
{
  "ok": true,
  "update": {
    "id": "...",
    "version": "2.0.3",
    "min_app_version": "2.0.0",
    "message": "Update available",
    "severity": "info",
    "telegram_url": "https://t.me/...",
    "is_active": true,
    "force": false,
    "starts_at": "2026-02-07T08:00:00+00:00",
    "ends_at": null,
    "created_at": "2026-02-07T08:00:00+00:00"
  }
}
```

### `POST /api/updates/ack`
Mark an info update as acknowledged by a device or user.

Request body (JSON)
```json
{
  "update_id": "app_update_id",
  "device_id": "device-123",
  "user_id": "optional"
}
```

Response `200`
```json
{ "ok": true }
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



## Typical frontend flow
1) `POST /api/subtitles` with `url`.
2) Poll `GET /api/subtitles/{video_id}/status` until `status=done`.
3) Fetch result via `GET /api/subtitles/{video_id}`.

## Update checks (mobile client)
- On app resume (from background), call `GET /api/updates/latest`.
- Always make a fresh API request (no client-side caching or time throttling).
- If response is `critical` (or `force=true`), block usage until updated.
- If response is `info`, show a dismissible banner and send `POST /api/updates/ack` on close.

## Environment settings that affect API
- `DOWNLOADING_EXPIRE_TIME` (seconds, default 3600): TTL for status/processing keys; cached subtitles are stored for `2x` this time.
- `RATE_LIMIT_MAX_REQUESTS` (default 50): max requests per window for rate limited endpoints.
- `RATE_LIMIT_WINDOW` (default 3600 seconds): rate limit window length.
- `MAX_AUDIO_DURATION` (seconds, default 1800): max allowed video duration.
- `VIDEO_CATALOG_COLLECTION` (default `videos`): MongoDB collection used as the video catalog source for `GET /api/videos`.
- `VIDEO_CATALOG_CACHE_KEY` (default `videos:all`): Redis key for the cached video list.
- `VIDEO_CATALOG_CACHE_TTL_SEC` (default `600`): TTL for video list cache; background refresher runs on this interval.
- `WEB_CONCURRENCY` (default `2`): number of Uvicorn worker processes (Docker).
- `YTDLP_MAX_CONCURRENT` (default `2`): max parallel yt-dlp operations.
- `RQ_QUEUE_NAME` (default `subtitles`): RQ queue for subtitle jobs.

## Errors
Common errors:
- `400` invalid input.
- `404` subtitles missing.
- `429` rate limit exceeded.
- `500` unexpected server error.

# MongoDB Data Schema (Draft)

> Draft schema for user monitoring, subtitles, and English-learning progress.

## Session storage (Redis)
Active sessions are stored in Redis (key prefix `session:`) with TTL (`SESSION_TTL_SEC`).
MongoDB does not persist sessions in the current setup.

## Collections

### users
- _id (device_id for anonymous users)
- username
- email | provider_id
- created_at
- updated_at
- last_login_at
- locale
- timezone
- flags (blocked, admin, etc.)
- session_id (last)
- device_id (last)
- app_version (last)
- platform (last)
- country (last)
- ip (last)

#### MVP note
- For anonymous usage, use `device_id` as the user `_id` so each device is a distinct user.

### videos
- _id
- video_id (unique, e.g., YouTube id)
- source_url
- title
- uploader
- channel_id
- channel_title
- thumbnail_url
- tags (array)
- category
- language_detected
- duration_sec
- source (string, source type/origin if needed)
- created_at
- updated_at
- scan:
  - last_scanned_at
  - scan_status (ok|error)
  - scan_error
- added_by_user_id (who added the video)
- added_at
- is_public (default true)

### videos (catalog source)
Collection used by `GET /api/videos` as the source of available videos. Documents are returned as-is
(with `_id` normalized to `id`, and `datetime`/`ObjectId` fields converted to JSON-friendly values).
The schema is intentionally flexible; include fields needed for frontend cards (e.g. title, thumbnail_url,
duration_sec, uploader).

### subtitle_jobs
- _id
- video_id (ref videos.video_id)
- user_id (who requested)
- subtitle_id (set when done)
- status (queued|processing|done|error)
- requested_at
- started_at
- finished_at
- queue_time_sec
- download_time_sec
- asr_time_sec
- postprocess_time_sec
- config:
  - asr_model
  - model_version
  - language
  - format (json|srt|vtt|text)
  - sample_rate
  - channels
- error_code
- error_message
- error_stage (download|asr|postprocess)
- error_stack (truncated)
- is_retryable
- retry_count
- worker_id
- runtime_sec

### subtitles
- _id
- video_id
- user_id (who generated)
- job_id
- generated_at
- format (json|srt|vtt|text)
- text (full text, optional)
- segments:
  - start_ms
  - end_ms
  - text
  - confidence
- config:
  - asr_model
  - model_version
  - language
  - sample_rate
  - channels
- language (duplicate of config.language for easier indexing)
- version (int, default 1)
- size_bytes (int)
- content_hash
- pipeline_version
- quality_score
- diarization (optional)
- word_timestamps (optional)

### user_activity_log
- _id
- user_id
- event (login, request_subtitles, view_video, save_word, etc.)
- video_id (optional)
- session_id
- device_id
- app_version
- platform
- country
- ip
- created_at
- meta (ip, user_agent, latency_ms, payload_size, etc.)

### user_stats
- _id (user_id)
- total_minutes_watched
- total_videos_watched
- total_videos_saved
- total_words_translated
- total_words_saved
- unique_words_seen
- words_reviewed
- minutes_today
- minutes_week
- streak_days
- last_active_at
- last_streak_reset_at

### user_vocab
- _id
- user_id
- items:
  - term
  - lemma
  - part_of_speech
  - translation
  - example_sentence
  - source_video_id
  - timestamp_sec
  - added_at
  - tags
  - mastery_level
  - next_review_at

### user_video_progress
- _id
- user_id
- video_id
- last_position_sec
- watch_time_sec
- speed
- last_session_id
- completion_percent
- words_translated_count
- words_saved_count
- last_watched_at
- subtitle_id

### watch_event
- _id
- user_id
- video_id
- event_type (start|pause|seek|progress|complete)
- timecode_sec
- occurred_at
- subtitle_id (optional)
- meta (json)

### watch_progress
- _id (or compound key user_id + video_id)
- user_id
- video_id
- last_timecode_sec
- last_viewed_at
- status (in_progress|completed|abandoned)
- subtitle_id (optional)

### user_saved_videos
- _id
- user_id
- video_id
- saved_at
- note
- tags

### user_watched_videos
- _id
- user_id
- video_id
- last_watched_at
- total_watch_time_sec

### app_updates
- _id
- version
- min_app_version
- max_app_version
- message
- severity (info|critical)
- telegram_url
- is_active
- force (bool)
- starts_at
- ends_at
- created_at

### update_ack
- _id
- update_id (ref app_updates._id)
- device_id
- user_id (optional)
- acked_at

### user_saved_words
- _id
- user_id
- term
- translation
- video_id (where it was saved)
- timecode_sec (where it was clicked)
- saved_at
- context_text (short snippet)
- lemma
- part_of_speech
- tags
- source (manual|auto)

### subscription_plan
- _id
- code (unique)
- name
- is_active
- base_duration_days
- created_at

### promo_code
- _id
- code (unique)
- description
- bonus_days
- overrides_plan_id (ref subscription_plan)
- valid_from
- valid_to
- max_uses_total
- max_uses_per_user
- is_active
- created_at
- times_used_total

### user_subscription
- _id
- user_id
- plan_id
- promo_code_id (optional)
- period (start/end range)
- status (trialing|active|canceled|expired|suspended|refunded|past_due)
- purchased_at
- activated_at
- canceled_at
- note
- provider
- provider_subscription_id
- provider_customer_id
- currency
- price_cents

### subscription_event
- _id
- user_subscription_id
- event_type
- occurred_at
- meta (json)

### audit_events
- _id
- user_id
- event
- entity_type
- entity_id
- diff (json)
- created_at

## Suggested Indexes
- videos.video_id (unique)
- videos.source
- videos.channel_id
- videos.added_by_user_id + added_at
- subtitle_jobs.video_id
- subtitle_jobs.user_id
- subtitle_jobs.status
- subtitle_jobs.worker_id
- subtitles.video_id
- subtitles.user_id
- subtitles.generated_at
- subtitles.video_id + language + version (unique)
- subtitles.content_hash
- subtitles.content (text or json) if full-text search is needed
- user_activity_log.user_id + created_at
- user_activity_log.session_id + created_at
- user_video_progress.user_id + video_id (unique)
- user_saved_videos.user_id + saved_at
- user_watched_videos.user_id + last_watched_at
- user_saved_words.user_id + saved_at
- user_saved_words.user_id + term
- watch_event.user_id + occurred_at
- watch_event.user_id + video_id + occurred_at
- watch_progress.user_id + last_viewed_at
- subscription_plan.code (unique)
- promo_code.code (unique)
- user_subscription.user_id + purchased_at
- subscription_event.user_subscription_id + occurred_at
- audit_events.user_id + created_at

## Notes
- If subtitle payloads are large, consider storing `subtitles` and `segments` separately.
- For monitoring logs, consider a TTL index on user_activity_log.created_at.
- For high-volume watch events, consider a TTL index on watch_event.occurred_at.

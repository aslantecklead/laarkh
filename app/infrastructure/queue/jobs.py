import asyncio

from app.application.subtitles_job import run_subtitles_job


def run_subtitle_job(url: str, video_id: str, expire_time: int, subtitle_job_id: str, user_id: str) -> None:
    asyncio.run(
        run_subtitles_job(
            url=url,
            video_id=video_id,
            expire_time=expire_time,
            job_id=subtitle_job_id,
            user_id=user_id,
        )
    )

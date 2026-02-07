from redis import Redis
from rq import Queue

from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB, RQ_QUEUE_NAME
from app.infrastructure.queue.jobs import run_subtitle_job


def _get_sync_redis() -> Redis:
    return Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def get_rq_queue() -> Queue:
    return Queue(name=RQ_QUEUE_NAME, connection=_get_sync_redis())


def enqueue_subtitle_job(url: str, video_id: str, expire_time: int, job_id: str, user_id: str) -> str:
    queue = get_rq_queue()
    job = queue.enqueue(
        run_subtitle_job,
        url=url,
        video_id=video_id,
        expire_time=expire_time,
        subtitle_job_id=job_id,
        user_id=user_id,
        job_id=job_id,
    )
    return job.id

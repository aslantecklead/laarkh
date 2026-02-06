import logging
import threading
import time

from app.config import VIDEO_CATALOG_CACHE_TTL_SEC
from app.infrastructure.video_catalog import get_video_catalog_use_case

log = logging.getLogger("app.video_catalog_refresher")


def start_video_catalog_refresher(interval_sec: int | None = None) -> threading.Thread:
    interval = interval_sec or VIDEO_CATALOG_CACHE_TTL_SEC
    use_case = get_video_catalog_use_case()

    def _loop() -> None:
        while True:
            try:
                videos, source = use_case.execute(force_refresh=True)
                log.info("Video catalog cache refreshed items=%d source=%s", len(videos), source)
            except Exception:
                log.exception("Video catalog cache refresh failed")
            time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread

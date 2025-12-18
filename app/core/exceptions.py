class VideoTooLongError(Exception):
    def __init__(self, duration: int, max_duration: int):
        self.duration = duration
        self.max_duration = max_duration
        super().__init__(f"Video duration {duration} seconds exceeds maximum allowed {max_duration} seconds")
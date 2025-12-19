from app.infrastructure.asr.whisper_asr import WhisperASR
from app.config import ASR_MODEL_SIZE


def get_asr_engine():
    """
    Factory function to create ASR engine instance
    """
    return WhisperASR(model_size=ASR_MODEL_SIZE)
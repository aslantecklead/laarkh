import whisper
from pathlib import Path
from typing import Dict, Any

class WhisperASR:
    def __init__(self, model_size="small"):
        """
        Initialize Whisper ASR model
        
        Args:
            model_size (str): Size of the model to load ("tiny", "base", "small", "medium", "large")
        """
        self.model = whisper.load_model(model_size)

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        """
        Transcribe audio file to text with timestamps
        
        Args:
            audio_path (Path): Path to the audio file
        
        Returns:
            Dict with transcription result including text, language and segments
        """
        result = self.model.transcribe(str(audio_path), word_timestamps=True)
        
        return {
            "text": result["text"],
            "language": result["language"],
            "segments": [
                {
                    "id": i,
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": [
                        {
                            "word": w["word"],
                            "start": w["start"],
                            "end": w["end"],
                            "confidence": w.get("probability", 1.0)
                        }
                        for w in seg.get("words", [])
                    ] if "words" in seg else []
                }
                for i, seg in enumerate(result["segments"])
            ]
        }
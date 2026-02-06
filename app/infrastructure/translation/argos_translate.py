import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

try:
    from argostranslate import package as argos_package
    from argostranslate import translate as argos_translate
    _ARGOS_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - optional dependency
    argos_package = None
    argos_translate = None
    _ARGOS_IMPORT_ERROR = exc

logger = logging.getLogger(__name__)

_TAG_PATTERN = re.compile(r"<(\d+)>(.*?)</\1>", re.DOTALL)


class ArgosTranslateError(RuntimeError):
    pass


class ArgosTranslator:
    def __init__(self, *, auto_download: bool = True) -> None:
        self._auto_download = auto_download
        self._lock = threading.Lock()
        self._translation_cache: Dict[Tuple[str, str], Any] = {}

    def translate_subtitles(
        self,
        subtitles: Dict[str, Any],
        *,
        target_language: str,
        source_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        if argos_translate is None:
            raise ArgosTranslateError(
                "argostranslate is not installed. Install it and restart the service."
            )

        source = (source_language or subtitles.get("language") or "en").strip().lower()
        target = (target_language or "ru").strip().lower()

        segments = subtitles.get("segments") or []
        translation = self._get_translation(source, target)

        translated_segments, translated_text, mode = self._translate_segments(segments, translation)

        return {
            "text": translated_text,
            "language": target,
            "segments": translated_segments,
            "meta": {
                "engine": "argos-translate",
                "source_language": source,
                "target_language": target,
                "mode": mode,
                "segments_total": len(segments),
                "segments_translated": len(translated_segments),
            },
        }

    def _get_translation(self, source: str, target: str):
        with self._lock:
            cached = self._translation_cache.get((source, target))
            if cached is not None:
                return cached

            if not self._has_installed_pair(source, target):
                if not self._auto_download:
                    raise ArgosTranslateError(
                        f"Argos model {source}->{target} not installed and auto-download is disabled."
                    )
                self._install_pair(source, target)

            translation = self._build_translation(source, target)
            self._translation_cache[(source, target)] = translation
            return translation

    def _has_installed_pair(self, source: str, target: str) -> bool:
        if argos_translate is None:
            return False
        languages = argos_translate.get_installed_languages()
        from_lang = next((lang for lang in languages if lang.code == source), None)
        to_lang = next((lang for lang in languages if lang.code == target), None)
        if from_lang is None or to_lang is None:
            return False
        try:
            return from_lang.get_translation(to_lang) is not None
        except Exception:
            return False

    def _build_translation(self, source: str, target: str):
        languages = argos_translate.get_installed_languages()
        from_lang = next((lang for lang in languages if lang.code == source), None)
        to_lang = next((lang for lang in languages if lang.code == target), None)
        if from_lang is None or to_lang is None:
            raise ArgosTranslateError(
                f"Installed Argos languages missing for {source}->{target}."
            )
        translation = from_lang.get_translation(to_lang)
        if translation is None:
            raise ArgosTranslateError(
                f"Argos translation not available for {source}->{target}."
            )
        return translation

    def _install_pair(self, source: str, target: str) -> None:
        if argos_package is None:
            raise ArgosTranslateError(
                "argostranslate is not installed. Install it and restart the service."
            )
        logger.info("Argos model %s->%s not found. Downloading...", source, target)
        argos_package.update_package_index()
        available_packages = argos_package.get_available_packages()
        candidates = [
            pkg for pkg in available_packages
            if getattr(pkg, "from_code", None) == source and getattr(pkg, "to_code", None) == target
        ]
        if not candidates:
            raise ArgosTranslateError(
                f"No Argos package available for {source}->{target}."
            )
        candidates.sort(key=_package_size)
        pkg = candidates[0]
        path = pkg.download()
        argos_package.install_from_path(path)
        logger.info("Argos model %s->%s installed.", source, target)

    def _translate_segments(self, segments: List[Dict[str, Any]], translation) -> Tuple[List[Dict[str, Any]], str, str]:
        if not segments:
            return [], "", "empty"

        tagged_text, id_map = _build_tagged_text(segments)
        try:
            translated_tagged = translation.translate(tagged_text)
        except Exception as exc:
            logger.warning("Tagged translation failed: %s", exc)
            translated_tagged = None

        if translated_tagged:
            parsed = _parse_tagged_translation(translated_tagged, id_map)
            if parsed is not None:
                translated_text = _join_translated_text(parsed)
                return parsed, translated_text, "tagged"

        # Fallback: translate each segment individually
        translated_segments: List[Dict[str, Any]] = []
        for idx, seg in enumerate(segments):
            seg_text = (seg.get("text") or "").strip()
            translated = translation.translate(seg_text) if seg_text else ""
            translated_segments.append(_copy_segment(seg, translated, idx))

        translated_text = _join_translated_text(translated_segments)
        return translated_segments, translated_text, "segment"


def _package_size(pkg: Any) -> float:
    size = getattr(pkg, "package_size", None)
    if isinstance(size, (int, float)):
        return float(size)
    if isinstance(size, str):
        try:
            return float(size)
        except ValueError:
            return float("inf")
    return float("inf")


def _build_tagged_text(segments: List[Dict[str, Any]]) -> Tuple[str, Dict[int, Dict[str, Any]]]:
    parts: List[str] = []
    id_map: Dict[int, Dict[str, Any]] = {}
    for idx, seg in enumerate(segments):
        seg_text = (seg.get("text") or "").strip()
        id_map[idx] = seg
        parts.append(f"<{idx}>{seg_text}</{idx}>")
    return " ".join(parts), id_map


def _parse_tagged_translation(translated: str, id_map: Dict[int, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    matches = _TAG_PATTERN.findall(translated)
    if not matches:
        return None
    translated_segments: List[Dict[str, Any]] = []
    parsed_by_idx: Dict[int, str] = {}

    for idx_str, text in matches:
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        parsed_by_idx[idx] = text.strip()

    if len(parsed_by_idx) < len(id_map):
        return None

    for idx in range(len(id_map)):
        original = id_map[idx]
        translated_text = parsed_by_idx.get(idx, "")
        translated_segments.append(_copy_segment(original, translated_text, idx))

    return translated_segments


def _copy_segment(original: Dict[str, Any], translated_text: str, fallback_id: int) -> Dict[str, Any]:
    return {
        "id": original.get("id", fallback_id),
        "start": original.get("start"),
        "end": original.get("end"),
        "text": translated_text,
    }


def _join_translated_text(segments: List[Dict[str, Any]]) -> str:
    return " ".join([seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip()])


_TRANSLATOR_INSTANCE: Optional[ArgosTranslator] = None
_TRANSLATOR_LOCK = threading.Lock()


def get_argos_translator(auto_download: bool = True) -> ArgosTranslator:
    global _TRANSLATOR_INSTANCE
    with _TRANSLATOR_LOCK:
        if _TRANSLATOR_INSTANCE is None:
            _TRANSLATOR_INSTANCE = ArgosTranslator(auto_download=auto_download)
        return _TRANSLATOR_INSTANCE

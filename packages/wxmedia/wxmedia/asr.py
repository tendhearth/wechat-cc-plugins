"""The ASR runner boundary. Concrete runners live behind this Protocol."""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AsrRunner(Protocol):
    model_id: str
    def transcribe(self, wav_path: str) -> str: ...


_WHISPER = {"whisper-small": "small", "whisper-large-v3": "large-v3"}
_cache = {}   # model_id -> WhisperModel (loading is expensive; reuse within a process)


def _default_transcribe(model_dir, model_id, wav_path):
    # faster-whisper fetches the model by name (into download_root=model_dir, once) and
    # decodes/infers. The map check runs BEFORE the import so an unmapped model errors
    # clearly without faster-whisper installed. language="zh" pinned (Whisper mis-detects
    # very short clips); CPU int8 for laptop footprint.
    if model_id not in _WHISPER:
        raise ValueError("wxmedia: no faster-whisper mapping for asr model %r" % model_id)
    from faster_whisper import WhisperModel
    if model_id not in _cache:
        _cache[model_id] = WhisperModel(_WHISPER[model_id], device="cpu",
                                        compute_type="int8", download_root=str(model_dir))
    segments, _info = _cache[model_id].transcribe(wav_path, language="zh")
    return "".join(s.text for s in segments).strip()


class FasterWhisperRunner:
    def __init__(self, model_manager, transcribe_fn=None):
        spec = model_manager.resolve("asr")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("asr"))
        self._fn = transcribe_fn or _default_transcribe

    def transcribe(self, wav_path):
        return self._fn(self._model_dir, self.model_id, wav_path)

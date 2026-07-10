"""The ASR runner boundary. Concrete runners live behind this Protocol."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class AsrRunner(Protocol):
    model_id: str
    def transcribe(self, wav_path: str) -> str: ...

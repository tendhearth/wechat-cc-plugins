"""The ASR runner boundary. Concrete runners live behind this Protocol."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class AsrRunner(Protocol):
    model_id: str
    def transcribe(self, wav_path: str) -> str: ...


import re
import subprocess
from pathlib import Path


def _parse_output(stdout: str) -> str:
    # SenseVoice/whisper.cpp print the transcript to stdout; strip an optional label.
    text = stdout.strip()
    m = re.match(r"^\s*(?:transcript|text)\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    return (m.group(1) if m else text).strip()


def _default_runner_cmd(model_dir: Path, wav_path: str) -> list:
    # Expected SenseVoice-GGUF self-contained binary; VERIFY against the real binary.
    binary = model_dir / ("sense-voice.exe" if __import__("os").name == "nt" else "sense-voice")
    return [str(binary), "-m", str(model_dir / "model.bin"), "-f", wav_path, "--no-timestamps"]


class SenseVoiceRunner:
    def __init__(self, model_manager, runner_cmd=None):
        spec = model_manager.resolve("asr")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("asr"))
        self._cmd = runner_cmd or _default_runner_cmd

    def transcribe(self, wav_path: str) -> str:
        cmd = self._cmd(self._model_dir, wav_path)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("ASR failed (%s): %s" % (proc.returncode, proc.stderr[:200]))
        return _parse_output(proc.stdout)

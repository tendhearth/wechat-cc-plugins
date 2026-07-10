"""WeChat SILK -> wav via pilk. WeChat prepends one byte to standard SILK v3."""
from pathlib import Path

_SILK_MAGIC = b"#!SILK_V3"


def fix_silk(blob: bytes) -> bytes:
    if blob[:len(_SILK_MAGIC)] == _SILK_MAGIC:
        return blob
    return blob[1:]   # drop WeChat's leading byte


def to_wav(voice_data: bytes, work_dir, name: str, rate: int = 16000, pilk_mod=None) -> Path:
    if pilk_mod is None:
        import pilk as pilk_mod
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    silk = work / (name + ".silk")
    wav = work / (name + ".wav")
    silk.write_bytes(fix_silk(voice_data))
    pilk_mod.silk_to_wav(str(silk), str(wav), rate)
    return wav

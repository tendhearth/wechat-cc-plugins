"""Orchestrate voice -> text: source -> silk -> asr -> store, incrementally."""
import sys
import time
from pathlib import Path

from .store import DerivedStore
from .voice_source import iter_voice
from .silk import to_wav


def transcribe_all(state_dir, runner, pilk_mod=None, limit=None, progress=None) -> dict:
    store = DerivedStore(state_dir)
    work = Path(state_dir) / "wxmedia" / "work"
    processed = skipped = failed = 0
    try:
        items = list(iter_voice(state_dir))
        total = len(items)
        for i, item in enumerate(items):
            if limit is not None and processed >= limit:
                break
            svr = item["svr_id"]
            if store.has(svr):
                skipped += 1
                continue
            wav = None
            try:
                wav = to_wav(item["voice_data"], work, svr, pilk_mod=pilk_mod)
                text = runner.transcribe(str(wav))
                store.put(svr, "voice", text, runner.model_id, int(time.time()))
                processed += 1
            except Exception as e:
                failed += 1
                sys.stderr.write("[wxmedia] transcribe failed svr=%s: %s\n" % (svr, e))
            finally:
                for ext in (".silk", ".wav"):
                    try:
                        (work / (str(svr) + ext)).unlink(missing_ok=True)
                    except OSError:
                        pass
            if progress is not None:
                progress(i + 1, total)
    finally:
        store.close()
    return {"processed": processed, "skipped": skipped, "failed": failed}

"""Lazy, injectable, verified model download into the state dir."""
import hashlib
from pathlib import Path
from urllib.request import urlopen


class NoArtifactError(Exception): ...
class DownloadDeclined(Exception): ...
class DownloadFailed(Exception): ...
class ChecksumError(Exception): ...


def model_dir(models_root, spec) -> Path:
    return Path(models_root) / spec.capability / spec.id


def is_present(models_root, spec) -> bool:
    return (model_dir(models_root, spec) / ".done").exists()


def _default_fetcher(url: str, dest: Path) -> None:
    # ModelScope pseudo-URL "modelscope://<repo>/<file?>" -> resolve to https.
    real = _modelscope_to_https(url) if url.startswith("modelscope://") else url
    with urlopen(real, timeout=60) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def _modelscope_to_https(url: str) -> str:
    repo = url[len("modelscope://"):]
    return "https://modelscope.cn/models/%s/resolve/master" % repo


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure(models_root, spec, platform, fetcher=None, confirm=None) -> Path:
    art = spec.artifact_for(platform)
    if art is None:
        raise NoArtifactError("%s has no artifact for %s" % (spec.id, platform))
    d = model_dir(models_root, spec)
    if is_present(models_root, spec):
        return d
    d.mkdir(parents=True, exist_ok=True)

    # Zero-URL artifact (e.g. OS-provided Apple Vision): mark present, no fetch.
    if not art.source_urls:
        (d / ".done").write_text("ok", encoding="utf-8")
        return d

    if confirm is not None and not confirm(art.size_mb):
        raise DownloadDeclined("user declined download of %s (%d MB)" % (spec.id, art.size_mb))

    fetch = fetcher or _default_fetcher
    dest = d / "model.bin"
    last_err = None
    for url in art.source_urls:
        try:
            fetch(url, dest)
            break
        except Exception as e:  # try next mirror
            last_err = e
    else:
        raise DownloadFailed("all sources failed for %s: %s" % (spec.id, last_err))

    if art.sha256 is not None:
        got = _sha256(dest)
        if got != art.sha256:
            dest.unlink(missing_ok=True)
            raise ChecksumError("%s sha256 mismatch: %s != %s" % (spec.id, got, art.sha256))

    (d / ".done").write_text("ok", encoding="utf-8")
    return d

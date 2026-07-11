import hashlib
import pytest
from model_manager.registry import ModelSpec, Artifact
from model_manager.download import (
    ensure, is_present, model_dir,
    NoArtifactError, DownloadDeclined, DownloadFailed, ChecksumError,
)

def _spec(size=10, sha=None, urls=("modelscope://x", "https://hf/x")):
    return ModelSpec(id="m1", capability="asr", tier="light", runtime="llama.cpp",
                     artifacts=(Artifact("any", list(urls), size_mb=size, sha256=sha),))

def test_ensure_downloads_when_missing(tmp_path):
    calls = []
    def fake(url, dest):
        calls.append(url); dest.write_bytes(b"weights")
    d = ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    assert d == model_dir(tmp_path, _spec())
    assert (d / "model.bin").read_bytes() == b"weights"
    assert is_present(tmp_path, _spec())
    assert len(calls) == 1  # first URL succeeded

def test_ensure_skips_when_present(tmp_path):
    calls = []
    def fake(url, dest): calls.append(url); dest.write_bytes(b"w")
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)  # second call
    assert len(calls) == 1  # not re-downloaded

def test_ensure_falls_back_to_next_url(tmp_path):
    def fake(url, dest):
        if url.startswith("modelscope"):
            raise OSError("modelscope down")
        dest.write_bytes(b"w")
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    assert is_present(tmp_path, _spec())

def test_ensure_raises_when_all_urls_fail(tmp_path):
    def fake(url, dest): raise OSError("nope")
    with pytest.raises(DownloadFailed):
        ensure(tmp_path, _spec(), "win-x64", fetcher=fake)

def test_ensure_refuses_network_download_without_sha256(tmp_path):
    # the REAL network path (no injected fetcher) must fail closed when the artifact
    # declares no sha256 — supply-chain integrity gate (raises before any urlopen).
    with pytest.raises(DownloadFailed):
        ensure(tmp_path, _spec(sha=None), "win-x64")


def test_ensure_verifies_sha256(tmp_path):
    good = hashlib.sha256(b"weights").hexdigest()
    def fake(url, dest): dest.write_bytes(b"weights")
    ensure(tmp_path / "case1", _spec(sha=good), "win-x64", fetcher=fake)  # passes
    def fake_bad(url, dest): dest.write_bytes(b"tampered")
    with pytest.raises(ChecksumError):
        ensure(tmp_path / "case2", _spec(sha=good), "win-x64", fetcher=fake_bad)

def test_ensure_respects_confirm_decline(tmp_path):
    def fake(url, dest): dest.write_bytes(b"w")
    with pytest.raises(DownloadDeclined):
        ensure(tmp_path, _spec(size=999), "win-x64", fetcher=fake, confirm=lambda mb: False)

def test_ensure_no_artifact_for_platform(tmp_path):
    spec = ModelSpec(id="m2", capability="ocr", tier="fixed", runtime="vision",
                     artifacts=(Artifact("mac-arm64", [], 0),))
    with pytest.raises(NoArtifactError):
        ensure(tmp_path, spec, "win-x64", fetcher=lambda u, d: None)

def test_ensure_zero_size_artifact_is_present_without_download(tmp_path):
    # e.g. Apple Vision: no files to fetch, but must count as present
    spec = ModelSpec(id="apple-vision", capability="ocr", tier="fixed", runtime="vision",
                     artifacts=(Artifact("mac-arm64", [], 0),))
    d = ensure(tmp_path, spec, "mac-arm64", fetcher=lambda u, dst: None)
    assert is_present(tmp_path, spec)
    assert d.exists()

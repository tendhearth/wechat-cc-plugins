#!/usr/bin/env python3
"""Minimal OpenAI-compatible LOCAL STT server (faster-whisper).

Serves `POST /v1/audio/transcriptions` (multipart `file` + `model`) → `{"text": ...}`,
the exact shape wechat-cc's daemon STT layer expects. Runs on this machine so the
app's mic audio never leaves it (data sovereignty). Reuses wxmedia's faster-whisper
— run with wxmedia's venv:

    HF_ENDPOINT=https://hf-mirror.com \
    packages/wxmedia/.venv/bin/python packages/wxmedia/stt_server.py

Env: STT_PORT (8001), STT_MODEL (small), STT_DEVICE (cpu), STT_COMPUTE (int8),
STT_DOWNLOAD_ROOT (HF cache dir), HF_ENDPOINT (mirror). Model loads once at startup
(downloads on first run, then cached).
"""
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("STT_PORT", "8001"))
MODEL = os.environ.get("STT_MODEL", "small")
DEVICE = os.environ.get("STT_DEVICE", "cpu")
COMPUTE = os.environ.get("STT_COMPUTE", "int8")

_model = None


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        kw = {"device": DEVICE, "compute_type": COMPUTE}
        root = os.environ.get("STT_DOWNLOAD_ROOT")
        if root:
            kw["download_root"] = root
        sys.stderr.write("[stt] loading faster-whisper '%s' (%s/%s)…\n" % (MODEL, DEVICE, COMPUTE))
        _model = WhisperModel(MODEL, **kw)
        sys.stderr.write("[stt] model ready\n")
    return _model


def _extract_file(headers, body):
    """Pull the `file` part out of a multipart/form-data body (stdlib only)."""
    ctype = headers.get("Content-Type", "")
    if "multipart/form-data" not in ctype or "boundary=" not in ctype:
        return None
    boundary = ("--" + ctype.split("boundary=", 1)[1].strip()).encode()
    for part in body.split(boundary):
        head, _, data = part.partition(b"\r\n\r\n")
        if b'name="file"' in head:
            return data.rsplit(b"\r\n", 1)[0]   # strip the trailing CRLF before the next boundary
    return None


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/models"):
            return self._json(200, {"ok": True, "model": MODEL})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/audio/transcriptions":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            audio = _extract_file(self.headers, body)
            if not audio:
                return self._json(400, {"error": "no `file` part in multipart body"})
            segments, _info = _load_model().transcribe(io.BytesIO(audio))
            text = "".join(s.text for s in segments).strip()
            self._json(200, {"text": text})
        except Exception as e:  # noqa: BLE001 — surface any failure as JSON, don't 500-crash the loop
            self._json(500, {"error": str(e)})

    def log_message(self, *_a):  # quiet the default access log
        pass


def main():
    _load_model()   # fail fast (download) before accepting requests
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write("[stt] OpenAI-compatible STT on http://127.0.0.1:%d/v1/audio/transcriptions\n" % PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()

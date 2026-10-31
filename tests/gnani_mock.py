"""Offline stand-in for the Gnani API: an httpx.MockTransport that replays hand-written replies.

Never touches the network and needs no API key. Every request it receives
is kept in ``MockGnani.requests`` so tests can check what would have been sent.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

FIXTURES = Path(__file__).parent / "fixtures" / "gnani"
FAKE_KEY = "test-key-not-real"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def wav_bytes(seconds: float = 1.0, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * sr), dtype="int16"), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class MockGnani:
    """Replies are given per path as a list (used in order, the last one repeated) or a callable."""

    def __init__(self, stt=None, tts=None):
        self.routes = {"/stt/v3": stt or [(200, fixture("stt_ok_v3.json"))],
                       "/api/v1/tts/inference": tts or [(200, wav_bytes())]}
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"message": "no such path"})
        if callable(route):
            return route(request)
        n = sum(1 for r in self.requests if r.url.path == request.url.path) - 1
        status, body, *headers = route[min(n, len(route) - 1)]
        headers = headers[0] if headers else {}
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers={"content-type": "audio/wav", **headers})
        return httpx.Response(status, json=body, headers=headers)


def make_client(mock: MockGnani, **kwargs):
    from voicebench.gnani.client import GnaniClient

    kwargs.setdefault("sleep", lambda s: None)
    kwargs.setdefault("jitter", lambda: 0.5)
    return GnaniClient(api_key=FAKE_KEY, transport=mock.transport, **kwargs)

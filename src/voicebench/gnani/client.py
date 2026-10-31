"""Thin HTTP client for Gnani's REST speech-to-text and text-to-speech endpoints.

- ``POST https://api.vachana.ai/stt/v3`` (multipart): ``audio_file``,
  ``language_code``, ``format`` and optionally ``model``. The JSON reply
  carries ``success``, ``request_id`` and ``transcript``; with
  ``prisma-v3.0`` also ``detected_language_code``, and ``truncated: true``
  when the transcript was cut short.
- ``POST https://api.vachana.ai/api/v1/tts/inference`` (JSON): ``text``,
  ``model``, ``voice``, ``language``, ``speed`` and ``audio_config``. A 200
  reply's body is the audio itself, in the container asked for.

Both authenticate with the ``X-API-Key-ID`` header. The key is read from the
``GNANI_API_KEY`` environment variable (or passed in by the caller) and is
never logged, stored in a run file or included in an error message.

Errors: 401 (``MISSING_API_KEY`` / ``INVALID_API_KEY``), 402 (insufficient
credit), 403 (``SCOPE_NOT_ALLOWED``) are never retried. 429
(``RATE_LIMITED``, no ``Retry-After`` header) is retried with exponential
backoff and jitter, up to ``max_attempts`` attempts in all. Timeouts and
5xx replies are not retried: the request may already have been processed
and charged.

``transport`` takes any ``httpx.BaseTransport`` (``httpx.MockTransport`` in
the tests), so nothing here needs the network to be exercised.
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

import httpx

API_KEY_ENV = "GNANI_API_KEY"
BASE_URL = "https://api.vachana.ai"
STT_PATH = "/stt/v3"
TTS_PATH = "/api/v1/tts/inference"
KEY_HEADER = "X-API-Key-ID"
REQUEST_ID_HEADER = "X-API-Request-ID"

STT_MODELS = ("prisma-v2.5", "prisma-v3.0")
STT_FORMATS = ("verbatim", "transcribe", "transliterate")
TTS_MODELS = ("timbre-v2.5", "timbre-v3.0")

# Response headers whose names contain one of these are kept with each
# request, in case the API reports credit use there. The documentation
# does not name any such header, so usually nothing is kept.
USAGE_HEADER_HINTS = ("credit", "usage", "balance", "billing", "cost", "quota")


class GnaniError(Exception):
    """Base class. ``status_code`` and ``error_code`` are None when no HTTP reply was received."""

    fatal = False  # True: every later request of the run would fail the same way

    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None,
                 request_id: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


class GnaniConfigError(GnaniError):
    """No API key, or an invalid option, found before any request was sent."""

    fatal = True


class GnaniAuthError(GnaniError):
    """401: missing or invalid API key."""

    fatal = True


class GnaniInsufficientCredit(GnaniError):
    """402: the account is out of credit. Hard stop for the whole run."""

    fatal = True


class GnaniScopeError(GnaniError):
    """403: the key is not allowed to use this endpoint or model."""

    fatal = True


class GnaniRateLimited(GnaniError):
    """429 on every attempt."""


class GnaniTimeout(GnaniError):
    """No reply within the timeout (not retried: the request may have been charged)."""


class GnaniAPIError(GnaniError):
    """Any other non-200 reply, a transport failure, or a reply that is not what the docs describe."""


_STATUS_ERRORS: dict[int, type[GnaniError]] = {
    401: GnaniAuthError,
    402: GnaniInsufficientCredit,
    403: GnaniScopeError,
    429: GnaniRateLimited,
}


def api_key_from_env(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    key = (env.get(API_KEY_ENV) or "").strip()
    if not key:
        raise GnaniConfigError(
            f"{API_KEY_ENV} is not set. Gnani runs need an API key from app.gnani.ai, "
            f"given only through the {API_KEY_ENV} environment variable (never on the command line "
            "or in a file under version control)."
        )
    return key


def _error_code(body: Any) -> Optional[str]:
    """Machine-readable code of an error reply: ``error_code``, ``code`` or ``error``, top level or under ``detail``."""
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if isinstance(detail, dict):
        body = detail
    for k in ("error_code", "code", "error"):
        if isinstance(body.get(k), str) and body[k]:
            return body[k]
    return None


def _error_message(body: Any, text: str) -> str:
    if isinstance(body, dict):
        for src in (body, body.get("detail") if isinstance(body.get("detail"), dict) else {}):
            for k in ("message", "detail", "error_description"):
                if isinstance(src.get(k), str) and src[k]:
                    return src[k]
    return text.strip()[:300]


def usage_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if any(h in k.lower() for h in USAGE_HEADER_HINTS)}


@dataclass
class Reply:
    """A 200 reply: JSON (STT) or audio bytes (TTS), plus what was learnt about the request."""

    status_code: int
    request_id: str
    attempts: int
    elapsed_ms: float
    json: Optional[dict[str, Any]] = None
    content: bytes = b""
    content_type: Optional[str] = None
    usage_headers: dict[str, str] = field(default_factory=dict)


class GnaniClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 20.0,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._key = api_key if api_key is not None else api_key_from_env()
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self._sleep = sleep
        self._jitter = jitter
        self._http = httpx.Client(transport=transport, timeout=timeout_s)
        # Every HTTP request sent, including 429s that were retried.
        self.http_attempts = 0

    def __repr__(self) -> str:  # never show the key
        return f"GnaniClient(base_url={self.base_url!r}, timeout_s={self.timeout_s}, max_attempts={self.max_attempts})"

    def close(self) -> None:
        self._http.close()

    def _scrub(self, s: str) -> str:
        return s.replace(self._key, "***") if self._key else s

    def backoff_s(self, attempt: int) -> float:
        """Wait after the ``attempt``-th 429: base * 2**(attempt-1), times a jitter factor in [0.5, 1.5)."""
        return min(self.backoff_max_s, self.backoff_base_s * 2 ** (attempt - 1)) * (0.5 + self._jitter())

    def _post(self, path: str, request_id: Optional[str], **kwargs: Any) -> Reply:
        rid = request_id or uuid.uuid4().hex
        headers = {KEY_HEADER: self._key, REQUEST_ID_HEADER: rid, **kwargs.pop("headers", {})}
        start = time.perf_counter()
        for attempt in range(1, self.max_attempts + 1):
            self.http_attempts += 1
            try:
                resp = self._http.post(f"{self.base_url}{path}", headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                raise GnaniTimeout(f"no reply from {path} within {self.timeout_s:g} s ({type(exc).__name__})",
                                   request_id=rid) from None
            except httpx.HTTPError as exc:
                raise GnaniAPIError(self._scrub(f"{path}: {type(exc).__name__}: {exc}"), request_id=rid) from None
            if resp.status_code == 200:
                return Reply(status_code=200, request_id=rid, attempts=attempt,
                             elapsed_ms=(time.perf_counter() - start) * 1000, content=resp.content,
                             content_type=resp.headers.get("content-type"),
                             usage_headers=usage_headers(resp.headers))
            try:
                body: Any = resp.json()
            except ValueError:
                body = None
            code = _error_code(body)
            if resp.status_code == 429 and attempt < self.max_attempts:
                self._sleep(self.backoff_s(attempt))
                continue
            cls = _STATUS_ERRORS.get(resp.status_code, GnaniAPIError)
            msg = _error_message(body, resp.text)
            what = {
                GnaniAuthError: "authentication failed; check GNANI_API_KEY",
                GnaniInsufficientCredit: "insufficient credit; the run is stopped. Top up or wait at app.gnani.ai",
                GnaniScopeError: "this key is not allowed to use this endpoint or model",
                GnaniRateLimited: f"rate limited on all {self.max_attempts} attempts",
            }.get(cls, "request failed")
            raise cls(self._scrub(f"{path}: HTTP {resp.status_code}{f' {code}' if code else ''}: {what}"
                                  f"{f' ({msg})' if msg else ''}"),
                      status_code=resp.status_code, error_code=code, request_id=rid)
        raise AssertionError("unreachable")

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        *,
        language_code: str,
        model: Optional[str] = None,
        format: str = "verbatim",
        request_id: Optional[str] = None,
    ) -> Reply:
        """Speech to text. ``model=None`` uses the API's default model."""
        if model is not None and model not in STT_MODELS:
            raise GnaniConfigError(f"unknown STT model {model!r}; expected one of {STT_MODELS}")
        if format not in STT_FORMATS:
            raise GnaniConfigError(f"format must be one of {STT_FORMATS}")
        if not language_code:
            raise GnaniConfigError("language_code is required")
        if "," in language_code or language_code == "indic-auto":
            if model != "prisma-v3.0":
                raise GnaniConfigError(f"language_code {language_code!r} needs model 'prisma-v3.0'")
            if "," in language_code and not 1 <= len(language_code.split(",")) <= 4:
                raise GnaniConfigError("a language_code list takes 1 to 4 codes")
        data = {"language_code": language_code, "format": format}
        if model is not None:
            data["model"] = model
        reply = self._post(STT_PATH, request_id, data=data, files={"audio_file": (filename, audio)})
        try:
            body = json.loads(reply.content)
        except ValueError:
            raise GnaniAPIError(f"{STT_PATH}: 200 reply is not JSON", request_id=reply.request_id) from None
        if not isinstance(body, dict) or not isinstance(body.get("transcript"), str):
            raise GnaniAPIError(f"{STT_PATH}: 200 reply has no 'transcript' string", request_id=reply.request_id)
        if body.get("success") is False:
            raise GnaniAPIError(f"{STT_PATH}: reply says success=false", request_id=reply.request_id)
        reply.json = body
        return reply

    def synthesize(
        self,
        text: str,
        *,
        model: str,
        voice: str,
        language: str,
        speed: float = 1.0,
        sample_rate: int = 16000,
        request_id: Optional[str] = None,
    ) -> Reply:
        """Text to speech, as 16-bit mono linear-PCM WAV bytes in ``reply.content``."""
        if model not in TTS_MODELS:
            raise GnaniConfigError(f"unknown TTS model {model!r}; expected one of {TTS_MODELS}")
        if not text.strip():
            raise GnaniConfigError("text is empty")
        body = {
            "text": text,
            "model": model,
            "voice": voice,
            "language": language,
            "speed": speed,
            "audio_config": {
                "sample_rate": sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "wav",
            },
        }
        reply = self._post(TTS_PATH, request_id, json=body)
        if not reply.content.startswith(b"RIFF"):
            raise GnaniAPIError(f"{TTS_PATH}: 200 reply is not a WAV file "
                                f"(content-type {reply.content_type})", request_id=reply.request_id)
        return reply

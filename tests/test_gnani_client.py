"""Gnani client: request construction, error mapping and 429 backoff. Offline (mock transport)."""

import json

import httpx
import pytest

from gnani_mock import FAKE_KEY, MockGnani, fixture, make_client, wav_bytes
from voicebench.gnani.client import (
    API_KEY_ENV,
    GnaniAPIError,
    GnaniAuthError,
    GnaniClient,
    GnaniConfigError,
    GnaniInsufficientCredit,
    GnaniRateLimited,
    GnaniScopeError,
    GnaniTimeout,
    api_key_from_env,
)


def _form(request: httpx.Request) -> tuple[dict[str, str], dict[str, bytes]]:
    """Fields and files of a multipart request body."""
    ctype = request.headers["content-type"]
    boundary = ctype.split("boundary=")[1].encode()
    fields, files = {}, {}
    for part in request.content.split(b"--" + boundary):
        if b"Content-Disposition" not in part:
            continue
        head, _, body = part.partition(b"\r\n\r\n")
        body = body.rstrip(b"\r\n")
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        if b"filename=" in head:
            files[name] = body
        else:
            fields[name] = body.decode()
    return fields, files


def test_key_comes_from_the_environment_only(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(GnaniConfigError, match="GNANI_API_KEY is not set"):
        GnaniClient()
    with pytest.raises(GnaniConfigError):
        api_key_from_env({API_KEY_ENV: "   "})
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    c = GnaniClient(transport=MockGnani().transport)
    assert FAKE_KEY not in repr(c)


def test_stt_request_construction():
    mock = MockGnani()
    c = make_client(mock)
    audio = wav_bytes(0.5)
    reply = c.transcribe(audio, "v1-002.wav", language_code="hi-IN,en-IN", model="prisma-v3.0",
                         request_id="rid-1")
    req = mock.requests[0]
    assert req.method == "POST" and str(req.url) == "https://api.vachana.ai/stt/v3"
    assert req.headers["X-API-Key-ID"] == FAKE_KEY
    assert req.headers["X-API-Request-ID"] == "rid-1"
    assert req.headers["content-type"].startswith("multipart/form-data")
    fields, files = _form(req)
    assert fields == {"language_code": "hi-IN,en-IN", "format": "verbatim", "model": "prisma-v3.0"}
    assert files["audio_file"] == audio
    assert reply.json["transcript"] == fixture("stt_ok_v3.json")["transcript"]
    assert reply.attempts == 1 and reply.request_id == "rid-1"


def test_stt_default_model_is_omitted():
    mock = MockGnani(stt=[(200, fixture("stt_ok_v25.json"))])
    make_client(mock).transcribe(wav_bytes(), "a.wav", language_code="en-IN")
    fields, _ = _form(mock.requests[0])
    assert "model" not in fields and fields["language_code"] == "en-IN"


@pytest.mark.parametrize("kwargs", [
    {"language_code": "hi-IN,en-IN"},  # a list needs prisma-v3.0
    {"language_code": "indic-auto", "model": "prisma-v2.5"},
    {"language_code": "a,b,c,d,e", "model": "prisma-v3.0"},
    {"language_code": "", "model": "prisma-v3.0"},
    {"language_code": "hi-IN", "model": "whisper"},
    {"language_code": "hi-IN", "format": "codemix-xyz"},
])
def test_stt_options_refused_before_sending(kwargs):
    mock = MockGnani()
    with pytest.raises(GnaniConfigError):
        make_client(mock).transcribe(wav_bytes(), "a.wav", **kwargs)
    assert mock.requests == []


def test_tts_request_construction():
    mock = MockGnani()
    reply = make_client(mock).synthesize("namaste", model="timbre-v2.5", voice="Nalini", language="hi-IN", speed=1.0)
    req = mock.requests[0]
    assert str(req.url) == "https://api.vachana.ai/api/v1/tts/inference"
    assert req.headers["X-API-Key-ID"] == FAKE_KEY
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {
        "text": "namaste", "model": "timbre-v2.5", "voice": "Nalini", "language": "hi-IN", "speed": 1.0,
        "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }
    assert reply.content.startswith(b"RIFF")


def test_tts_non_wav_reply_is_an_error():
    mock = MockGnani(tts=[(200, {"audio": "not raw audio"})])
    with pytest.raises(GnaniAPIError, match="not a WAV"):
        make_client(mock).synthesize("hi", model="timbre-v2.5", voice="Kaveri", language="en-IN")


@pytest.mark.parametrize("status,name,cls,code", [
    (401, "err_401_invalid_key.json", GnaniAuthError, "INVALID_API_KEY"),
    (401, "err_401_missing_key.json", GnaniAuthError, "MISSING_API_KEY"),
    (402, "err_402_credit.json", GnaniInsufficientCredit, None),
    (403, "err_403_scope.json", GnaniScopeError, "SCOPE_NOT_ALLOWED"),
    (500, "err_403_scope.json", GnaniAPIError, "SCOPE_NOT_ALLOWED"),
])
def test_errors_are_mapped_and_never_retried(status, name, cls, code):
    sleeps = []
    mock = MockGnani(stt=[(status, fixture(name)), (200, fixture("stt_ok_v3.json"))])
    c = make_client(mock, sleep=sleeps.append)
    with pytest.raises(cls) as info:
        c.transcribe(wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert info.value.status_code == status and info.value.error_code == code
    assert info.value.fatal == (status in (401, 402, 403))
    assert len(mock.requests) == 1 and sleeps == [] and c.http_attempts == 1
    assert FAKE_KEY not in str(info.value)


def test_429_backs_off_with_jitter_then_succeeds():
    sleeps = []
    mock = MockGnani(stt=[(429, fixture("err_429_rate.json")), (429, fixture("err_429_rate.json")),
                          (200, fixture("stt_ok_v3.json"))])
    jitters = iter([0.0, 0.99])
    c = make_client(mock, sleep=sleeps.append, jitter=lambda: next(jitters), backoff_base_s=1.0)
    reply = c.transcribe(wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert reply.attempts == 3 and len(mock.requests) == 3 and c.http_attempts == 3
    # 1 s * 2**0 * 0.5, then 1 s * 2**1 * 1.49
    assert sleeps == pytest.approx([0.5, 2.98])
    # The same request id on every attempt.
    assert len({r.headers["X-API-Request-ID"] for r in mock.requests}) == 1


def test_429_is_bounded():
    sleeps = []
    mock = MockGnani(stt=[(429, fixture("err_429_rate.json"))])
    c = make_client(mock, sleep=sleeps.append, max_attempts=3)
    with pytest.raises(GnaniRateLimited) as info:
        c.transcribe(wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert len(mock.requests) == 3 and len(sleeps) == 2
    assert info.value.error_code == "RATE_LIMITED" and not info.value.fatal


def test_backoff_is_capped():
    c = make_client(MockGnani(), backoff_base_s=10, backoff_max_s=15, jitter=lambda: 0.5)
    assert c.backoff_s(1) == 10 and c.backoff_s(5) == 15


def test_timeout_is_not_retried():
    calls = []

    def slow(request):
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(GnaniTimeout):
        make_client(MockGnani(stt=slow), timeout_s=0.1).transcribe(
            wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert len(calls) == 1


def test_malformed_success_replies():
    for body in ({"success": True}, {"success": False, "transcript": "x"}):
        with pytest.raises(GnaniAPIError):
            make_client(MockGnani(stt=[(200, body)])).transcribe(wav_bytes(), "a.wav", language_code="hi-IN")
    not_json = MockGnani(stt=lambda r: httpx.Response(200, content=b"<html>"))
    with pytest.raises(GnaniAPIError, match="not JSON"):
        make_client(not_json).transcribe(wav_bytes(), "a.wav", language_code="hi-IN")


def test_usage_headers_are_kept_only_when_present():
    mock = MockGnani(stt=[(200, fixture("stt_ok_v3.json"), {"X-Credits-Used": "3", "X-Other": "y"})])
    reply = make_client(mock).transcribe(wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert reply.usage_headers == {"x-credits-used": "3"}
    plain = make_client(MockGnani()).transcribe(wav_bytes(), "a.wav", language_code="hi-IN", model="prisma-v3.0")
    assert plain.usage_headers == {}


def test_key_is_scrubbed_from_error_text():
    body = {"message": f"bad key {FAKE_KEY}"}
    with pytest.raises(GnaniAuthError) as info:
        make_client(MockGnani(stt=[(401, body)])).transcribe(wav_bytes(), "a.wav", language_code="hi-IN")
    assert FAKE_KEY not in str(info.value) and "***" in str(info.value)

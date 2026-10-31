"""Budget guard for live Gnani runs.

A live run needs two things at once: the ``--live`` flag and a
``GNANI_API_KEY`` in the environment. Without ``--live`` the commands only
print what they would send. During a run every billable call (one STT
transcription, one TTS synthesis) first takes one unit from a
:class:`Budget`; once ``max_requests`` are spent the next call raises
:class:`BudgetExceeded` and the run stops. 402 (out of credit), 401 and 403
stop the run too, as :class:`GnaniRunAborted`.

Both are ``voicebench.asr.ASRUnavailable``, which ``runner.run`` and
``realspeech.run_realspeech`` re-raise instead of recording a per-item
error, so a stopped run writes no run file.

The API does not report credit use in its documented responses; counts of
requests and audio seconds are what can be measured here. Credit used must
be read off the Usage page at app.gnani.ai, before and after.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from voicebench.asr import ASRUnavailable
from voicebench.gnani.client import API_KEY_ENV, GnaniError, api_key_from_env

DEFAULT_MAX_REQUESTS = 10
USAGE_PAGE = "app.gnani.ai (Usage page)"


class LiveRunRefused(Exception):
    """A live run was asked for without both --live and GNANI_API_KEY."""


class BudgetExceeded(ASRUnavailable):
    """The run's request cap is spent."""


class GnaniRunAborted(ASRUnavailable):
    """A fatal API error (402 out of credit, 401, 403): every later request would fail the same way."""

    def __init__(self, error: GnaniError):
        super().__init__(str(error))
        self.error = error

    @property
    def out_of_credit(self) -> bool:
        return self.error.status_code == 402


def require_live(live: bool, env: Optional[Mapping[str, str]] = None) -> str:
    """The API key, if and only if the operator opted in with --live and set GNANI_API_KEY."""
    if not live:
        raise LiveRunRefused("not a live run: pass --live to call the Gnani API (requests use credit)")
    try:
        return api_key_from_env(env)
    except GnaniError as exc:
        raise LiveRunRefused(str(exc)) from None


class Budget:
    def __init__(self, max_requests: int = DEFAULT_MAX_REQUESTS):
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        self.max_requests = max_requests
        self.requests = 0
        self.stt_requests = 0
        self.tts_requests = 0
        self.audio_seconds_sent = 0.0
        self.tts_characters = 0
        self.log: list[dict[str, Any]] = []

    @property
    def remaining(self) -> int:
        return self.max_requests - self.requests

    def reserve(self, kind: str, item: str) -> dict[str, Any]:
        """Take one request from the budget before sending it; returns the log entry to fill in."""
        if kind not in ("stt", "tts"):
            raise ValueError(kind)
        if self.requests >= self.max_requests:
            raise BudgetExceeded(
                f"request cap reached ({self.max_requests}); not sending {kind} for {item}. "
                "Raise --max-requests deliberately if more are wanted."
            )
        self.requests += 1
        if kind == "stt":
            self.stt_requests += 1
        else:
            self.tts_requests += 1
        entry: dict[str, Any] = {"n": self.requests, "kind": kind, "item": item}
        self.log.append(entry)
        return entry

    def as_dict(self) -> dict[str, Any]:
        credit = {e["item"]: e["usage_headers"] for e in self.log if e.get("usage_headers")}
        out: dict[str, Any] = {
            "max_requests": self.max_requests,
            "requests": self.requests,
            "stt_requests": self.stt_requests,
            "tts_requests": self.tts_requests,
            "audio_seconds_sent": round(self.audio_seconds_sent, 3),
            "tts_characters": self.tts_characters,
            "request_log": self.log,
        }
        # Only when a reply actually carried such headers; nothing is estimated.
        if credit:
            out["credit_headers_by_item"] = credit
        else:
            out["credit_usage"] = f"not reported by the API; read the credit delta on {USAGE_PAGE}"
        return out

    def summary(self, http_attempts: Optional[int] = None) -> str:
        attempts = f", {http_attempts} HTTP attempts incl. 429 retries" if http_attempts is not None else ""
        return (
            f"gnani: {self.requests} of {self.max_requests} allowed requests used "
            f"({self.stt_requests} STT, {self.tts_requests} TTS{attempts}); "
            f"{self.audio_seconds_sent:.1f} s of audio sent to STT; {self.tts_characters} characters sent to TTS.\n"
            f"Check the credit used on {USAGE_PAGE}: compare it with the balance before this run."
        )


__all__ = ["API_KEY_ENV", "Budget", "BudgetExceeded", "GnaniRunAborted", "LiveRunRefused",
           "DEFAULT_MAX_REQUESTS", "require_live"]

"""The seam for plugging in your own language understanding.

By default every transcript goes to the built-in rule-based matcher
(``voicebench.nlu.matcher.match``). An *understander* replaces it:

    understand(transcript: str, domain: str) -> {"intent": str | None, "slots": {str: str}}

``domain`` is one of the built-in domain values ("banking", "food", "travel",
"support"). The returned dict must have exactly the keys "intent" and
"slots". Anything else, or an exception, is an error for that scenario and
counts as a task failure. There is no fallback to the built-in matcher.

An understander is named ``package.module:function`` and loaded by import,
so it runs with the full rights of this process. Only point it at trusted
local code.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

Understander = Callable[[str, str], Any]

# Recorded in the run file when the built-in matcher did the understanding.
BUILTIN = "builtin"


class UnderstanderError(Exception):
    """An understander raised, or returned something outside the contract."""


def understander_id(understand: Optional[Understander]) -> str:
    """``"builtin"`` for the default, else ``module:qualname`` of the callable."""
    if understand is None:
        return BUILTIN
    module = getattr(understand, "__module__", None) or "?"
    name = getattr(understand, "__qualname__", None) or type(understand).__qualname__
    return f"{module}:{name}"


def check_understanding(out: Any) -> tuple[Optional[str], dict[str, str]]:
    """Return ``(intent, slots)`` from an understander's output, or raise UnderstanderError."""
    if not isinstance(out, dict):
        raise UnderstanderError(f"expected a dict, got {type(out).__name__}")
    keys = set(out)
    if keys != {"intent", "slots"}:
        raise UnderstanderError(f"expected keys ['intent', 'slots'], got {sorted(map(str, keys))}")
    intent, slots = out["intent"], out["slots"]
    if intent is not None and not isinstance(intent, str):
        raise UnderstanderError(f"intent must be a str or None, got {type(intent).__name__}")
    if not isinstance(slots, dict):
        raise UnderstanderError(f"slots must be a dict, got {type(slots).__name__}")
    for k, v in slots.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise UnderstanderError(f"slots must map str to str, got {k!r}: {v!r}")
    return intent, dict(slots)


def understand_with(understand: Understander, transcript: str, domain: str) -> tuple[Optional[str], dict[str, str]]:
    """Call ``understand`` and check its output; any failure becomes UnderstanderError."""
    try:
        out = understand(transcript, domain)
    except Exception as exc:
        raise UnderstanderError(f"{type(exc).__name__}: {exc}") from exc
    return check_understanding(out)


def load_understander(spec: str) -> Understander:
    """Import ``package.module:function`` and return the callable.

    The module must be importable from this Python (installed, or on
    PYTHONPATH). Importing it runs its code.
    """
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"understander must look like 'package.module:function', got {spec!r}")
    module = importlib.import_module(module_name)
    obj: Any = module
    for part in attr.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            raise ValueError(f"{module_name!r} has no attribute {attr!r}") from None
    if not callable(obj):
        raise ValueError(f"{spec!r} is not callable")
    return obj

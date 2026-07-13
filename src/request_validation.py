"""webapp HTTP query validation without loading the RAG index or models."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import urllib.parse


MAX_REQUEST_TARGET_CHARS = 4096
MAX_QUERY_CHARS = 500
MAX_SCOPE_DEPTH = 8
MAX_SCOPE_SEGMENT_CHARS = 80
TOPK_MIN = 1
TOPK_MAX = 30
ALLOWED_TYPES = frozenset({"overview", "description", "glossary", "related", "qa"})
_TRUE = frozenset({"1", "true", "on"})
_FALSE = frozenset({"0", "false", "off"})
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:01[016789]|0\d{1,2})[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d(?:[- ]?\d){7,18}(?!\d)")


@dataclass(frozen=True)
class QueryParams:
    q: str
    alpha: float
    topk: int
    tau: float | None
    types: set[str] | None
    use_rerank: bool
    scope: list[str] | None
    src: str


def _one(values: dict[str, list[str]], name: str, default: str = "") -> str:
    found = values.get(name)
    if not found:
        return default
    if len(found) != 1:
        raise ValueError(f"duplicate parameter: {name}")
    return found[0]


def _finite_float(raw: str, name: str, lo: float, hi: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name}") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} out of range")
    return value


def parse_query_params(raw_query: str) -> QueryParams:
    if len(raw_query) > MAX_REQUEST_TARGET_CHARS:
        raise ValueError("request target too long")
    try:
        values = urllib.parse.parse_qs(
            raw_query, keep_blank_values=True, strict_parsing=False, max_num_fields=20)
    except ValueError:
        raise ValueError("too many query parameters") from None

    q = _one(values, "q").strip()
    if not q or len(q) > MAX_QUERY_CHARS or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in q):
        raise ValueError("invalid query")
    if _EMAIL_RE.search(q) or _PHONE_RE.search(q) or _LONG_NUMBER_RE.search(q):
        raise ValueError("query contains sensitive-looking data")

    alpha = _finite_float(_one(values, "alpha", "0.5"), "alpha", 0.0, 1.0)
    try:
        topk = int(_one(values, "topk", "5"))
    except ValueError:
        raise ValueError("invalid topk") from None
    if not TOPK_MIN <= topk <= TOPK_MAX:
        raise ValueError("topk out of range")

    tau_raw = _one(values, "tau")
    tau = _finite_float(tau_raw, "tau", 0.0, 1.0) if tau_raw else None

    type_values = [value for value in _one(values, "types").split(",") if value]
    types = set(type_values) or None
    if types and (len(type_values) != len(types) or not types <= ALLOWED_TYPES):
        raise ValueError("invalid chunk type")

    rerank_raw = _one(values, "rerank", "1").lower()
    if rerank_raw not in _TRUE | _FALSE:
        raise ValueError("invalid rerank flag")
    use_rerank = rerank_raw in _TRUE

    scope = [segment.strip() for segment in _one(values, "scope").split(">")
             if segment.strip()] or None
    if scope and (len(scope) > MAX_SCOPE_DEPTH
                  or any(len(segment) > MAX_SCOPE_SEGMENT_CHARS
                         or any(ord(ch) < 32 for ch in segment) for segment in scope)):
        raise ValueError("invalid scope")

    src = _one(values, "src")
    if src not in ("", "chip"):
        raise ValueError("invalid source")
    return QueryParams(q, alpha, topk, tau, types, use_rerank, scope, src)

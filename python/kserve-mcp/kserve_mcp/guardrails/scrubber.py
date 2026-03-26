"""Scrubs sensitive data from log output and inference responses before
returning results to the LLM context."""

import re
from typing import Any

# Patterns applied to string content before it leaves the server
_PATTERNS: list[tuple[str, str]] = [
    # Bearer tokens — must run before the generic key=value pattern so that
    # "Authorization: Bearer <token>" is fully replaced in one pass
    (
        r"(?i)(Authorization\s*[=:]\s*)?Bearer\s+[A-Za-z0-9\-._~+/]+=*",
        r"Bearer <REDACTED>",
    ),
    # key=value or key: value pairs with secret-sounding names
    (
        r"(?i)(password|passwd|secret|token|api[_\-]?key|auth(?:orization)?"
        r"|credential|private[_\-]?key|access[_\-]?key|client[_\-]?secret"
        r")[^\S\r\n]*[=:][^\S\r\n]*\S+",
        r"\1=<REDACTED>",
    ),
    # JWT tokens (three base64url segments separated by dots)
    (r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", r"<JWT_REDACTED>"),
    # IPv4 addresses (scrub to avoid leaking cluster-internal IPs)
    (r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", r"<IP_REDACTED>"),
    # AWS-style access key IDs
    (r"\b(AKIA|ASIA|AROA)[A-Z0-9]{16}\b", r"<AWS_KEY_REDACTED>"),
    # Generic hex secrets ≥32 chars (API keys, hashes)
    (r"\b[0-9a-fA-F]{32,}\b", r"<HEX_REDACTED>"),
]

_COMPILED = [(re.compile(p), r) for p, r in _PATTERNS]


def scrub(text: str) -> str:
    """Apply all redaction patterns to *text* and return cleaned string."""
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text


def scrub_dict(data: Any) -> Any:
    """Recursively scrub a dict/list/str value."""
    if isinstance(data, str):
        return scrub(data)
    if isinstance(data, dict):
        return {k: scrub_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [scrub_dict(item) for item in data]
    return data


def scrub_k8s_object(obj: dict) -> dict:
    """Remove known-sensitive fields from a raw k8s object dict and scrub
    the remainder, so ISVC specs with env var secrets don't leak."""
    if not isinstance(obj, dict):
        return obj

    # Drop entire env/envFrom blocks from containers — these commonly hold secrets
    def strip_containers(containers: list) -> list:
        cleaned = []
        for c in containers:
            c = dict(c)
            c.pop("env", None)
            c.pop("envFrom", None)
            cleaned.append(c)
        return cleaned

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            result = {}
            for k, v in node.items():
                if k in ("env", "envFrom"):
                    result[k] = "<REDACTED>"
                elif k == "containers":
                    result[k] = strip_containers(v) if isinstance(v, list) else walk(v)
                else:
                    result[k] = walk(v)
            return result
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return scrub(node)
        return node

    return walk(obj)

"""Runtime policy enforcement: namespace allow/block lists, read-only mode,
and destructive-operation confirmation."""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _blocked() -> frozenset[str]:
    raw = os.environ.get("KSERVE_MCP_BLOCKED_NAMESPACES", "kube-system,kube-public")
    return frozenset(n.strip() for n in raw.split(",") if n.strip())


@lru_cache(maxsize=1)
def _allowed() -> frozenset[str]:
    """If set, only these namespaces are permitted. Empty = allow all (minus blocked)."""
    raw = os.environ.get("KSERVE_MCP_ALLOWED_NAMESPACES", "")
    return frozenset(n.strip() for n in raw.split(",") if n.strip())


def is_readonly() -> bool:
    """Read-only check always re-reads the env var (supports runtime changes)."""
    return os.environ.get("KSERVE_MCP_READONLY", "false").lower() == "true"


def scrub_logs_enabled() -> bool:
    return os.environ.get("KSERVE_MCP_SCRUB_LOGS", "true").lower() == "true"


def scrub_inference_enabled() -> bool:
    return os.environ.get("KSERVE_MCP_SCRUB_INFERENCE", "true").lower() == "true"


class PolicyError(Exception):
    pass


def check_namespace(namespace: str) -> None:
    """Raise PolicyError if *namespace* is not permitted."""
    if namespace in _blocked():
        raise PolicyError(
            f"Namespace '{namespace}' is blocked by KSERVE_MCP_BLOCKED_NAMESPACES policy."
        )
    allowed = _allowed()
    if allowed and namespace not in allowed:
        raise PolicyError(
            f"Namespace '{namespace}' is not in the KSERVE_MCP_ALLOWED_NAMESPACES allow-list "
            f"({', '.join(sorted(allowed))})."
        )


def check_write(operation: str) -> None:
    """Raise PolicyError if the server is in read-only mode."""
    if is_readonly():
        raise PolicyError(
            f"Operation '{operation}' is not permitted: server is running in read-only mode "
            "(KSERVE_MCP_READONLY=true)."
        )


def require_confirmation(confirm: bool, description: str) -> str | None:
    """If *confirm* is False, return a preview string instead of proceeding.
    Returns None when the caller should proceed."""
    if not confirm:
        return (
            f"DRY RUN — the following action was NOT executed:\n{description}\n\n"
            "Re-call with confirm=True to apply."
        )
    return None

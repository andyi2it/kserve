from typing import Any
from . import isvc, scale, traffic, debug, inference


def register_all(mcp: Any) -> None:
    """Register every tool module with the MCP server instance."""
    isvc.register(mcp)
    scale.register(mcp)
    traffic.register(mcp)
    debug.register(mcp)
    inference.register(mcp)

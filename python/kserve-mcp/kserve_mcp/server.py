"""KServe MCP Server — HTTP/SSE transport.

Environment variables
---------------------
KSERVE_MCP_HOST                  Bind host (default: 0.0.0.0)
KSERVE_MCP_PORT                  Bind port (default: 8000)
KSERVE_MCP_READONLY              Set to 'true' to disable all write operations
KSERVE_MCP_BLOCKED_NAMESPACES    Comma-separated namespaces to deny (default: kube-system,kube-public)
KSERVE_MCP_ALLOWED_NAMESPACES    Comma-separated namespace allow-list (empty = allow all minus blocked)
KSERVE_MCP_SCRUB_LOGS            Set to 'false' to disable log scrubbing (default: true)
KSERVE_MCP_SCRUB_INFERENCE       Set to 'false' to disable inference response scrubbing (default: true)
"""

import logging
import os

from mcp.server.fastmcp import FastMCP

from .tools import register_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="kserve-mcp",
    instructions=(
        "You are a KServe assistant. You can list, create, scale, debug, and run "
        "inference against InferenceServices deployed on Kubernetes. "
        "Always confirm destructive operations (delete) before executing. "
        "Sensitive data in logs and inference responses is automatically redacted."
    ),
)

register_all(mcp)


def main() -> None:
    host = os.environ.get("KSERVE_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("KSERVE_MCP_PORT", "8000"))
    # host/port live on mcp.settings in this version of the SDK
    mcp.settings.host = host
    mcp.settings.port = port
    logger.info("Starting KServe MCP server on %s:%d (SSE transport)", host, port)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()

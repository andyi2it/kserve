FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

COPY kserve_mcp/ kserve_mcp/

EXPOSE 8000

ENV KSERVE_MCP_HOST=0.0.0.0
ENV KSERVE_MCP_PORT=8000
ENV KSERVE_MCP_READONLY=false
ENV KSERVE_MCP_SCRUB_LOGS=true
ENV KSERVE_MCP_SCRUB_INFERENCE=true

CMD ["python", "-m", "kserve_mcp.server"]

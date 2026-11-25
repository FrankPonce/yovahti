# Yövahti demo image: the MCP server on a small synthetic network (no operator data, no keys).
# Used by compose.yaml; see README "Try it in one command".
FROM python:3.12-slim

# LightGBM needs the OpenMP runtime, which the slim image leaves out
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts/demo_agent.py ./scripts/demo_agent.py
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

EXPOSE 8765
CMD ["python", "-m", "yovahti.mcp_server.server", "--demo", "--host", "0.0.0.0", "--port", "8765"]

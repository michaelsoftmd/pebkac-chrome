# Start from a clean Python image
FROM docker.io/python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Create dummy README to satisfy hatchling
RUN echo "# OpenAPI Tools" > README.md

# Install dependencies only (not the package, also no ddgs (duckduckgosearch, this blocks zendriver))
RUN uv pip install --system \
    fastapi>=0.115.2 \
    'uvicorn[standard]==0.35.0' \
    httpx>=0.25.1 \
    aiohttp>=3.9.1 \
    redis==6.2 \
    aiofiles>=23.2.1 \
    nest-asyncio>=1.5.8 \
    'smolagents[openai]==1.21.1' \
    pydantic>=2.0.0

# Copy application code
COPY . .

EXPOSE 9000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]

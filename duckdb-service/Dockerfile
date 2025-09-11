FROM docker.io/python:3.13-slim

WORKDIR /app

# Install system dependencies including curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.115.2 \
    uvicorn[standard]>=0.35.0 \
    duckdb>=1.3.2 \
    aiofiles>=24.1.0 \
    pydantic>=2.5.0

# Create data directory
RUN mkdir -p /data /cache

# Copy the service code
COPY duckdb_service.py .

# Expose port
EXPOSE 9001

# Run the service
CMD ["uvicorn", "duckdb_service:app", "--host", "0.0.0.0", "--port", "9001", "--log-level", "info"]

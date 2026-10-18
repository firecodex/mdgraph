# Multi-stage lightweight Python 3.12 image for MdGraph on Google Cloud Run
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install system dependencies (git is required for Git-backed OKF knowledge storage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Configure default Git author identity for automated compiler commits
RUN git config --global user.name "MdGraph Cloud Service" && \
    git config --global user.email "service@mdgraph.dev"

WORKDIR /app

# Copy packaging metadata
COPY pyproject.toml README.md LICENSE ./

# Copy source tree and install with REST API and PostgreSQL dependencies
COPY src/ ./src/
RUN pip install --no-cache-dir ".[api,postgres]"

# Initialize default knowledge repository structure
RUN mdgraph init ./knowledge

# Expose Cloud Run default port
EXPOSE 8080

# Default entrypoint starts the FastAPI REST service on 0.0.0.0:8080
# Can be overridden in Cloud Run args to run FastMCP ('serve') or workers
CMD ["mdgraph", "api", "--host", "0.0.0.0", "--port", "8080"]

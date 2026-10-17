FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies for asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY . .

# Dev images (docker-compose) also get the test tooling; a production build
# leaves INSTALL_DEV unset and stays lean. constraints.txt pins the versions of a
# known-good build: without it pip re-resolves the unpinned LangChain family against
# whatever was released since, and can give up (resolution-too-deep).
ARG INSTALL_DEV=false
RUN pip install --no-cache-dir --upgrade pip && \
    if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -c constraints.txt -e ".[dev]"; \
    else pip install --no-cache-dir -c constraints.txt -e .; fi

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn kairos_kb.main:app --host 0.0.0.0 --port 8000"]

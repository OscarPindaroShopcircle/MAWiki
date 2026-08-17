FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    UV_VERSION=0.7.8

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv==$UV_VERSION"

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
RUN mkdir -p /app && chown appuser:appuser /app

WORKDIR /app

ENV UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/tmp/venv

COPY --chown=appuser:appuser pyproject.toml uv.lock ./

USER appuser

RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.backend.server:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastapi>=0.115,<0.116" "uvicorn[standard]>=0.32,<0.33" \
      "sqlalchemy[asyncio]>=2.0,<2.1" asyncpg alembic psycopg2-binary \
      "pydantic[email]>=2.9" pydantic-settings argon2-cffi pyjwt

FROM base AS runtime
RUN useradd --create-home --uid 10001 app
COPY backend/ /app/
COPY infrastructure/db /infrastructure/db
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

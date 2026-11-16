# Multi-stage build (task T009): Node builds the SPA, Python serves API + static files.

FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
# The app image installs runtime dependencies only. The eval image passes
# UV_GROUPS="--group eval" to add RAGAS (docker-compose.yml service `eval`).
ARG UV_GROUPS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first for layer caching.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-default-groups $UV_GROUPS --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-default-groups $UV_GROUPS
COPY --from=frontend /build/dist /app/static

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory codecompass.main:app_factory --host 0.0.0.0 --port 8000"]

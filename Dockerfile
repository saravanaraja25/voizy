# syntax=docker/dockerfile:1
# Targets: api (control plane), agent (voice worker). The dashboard has its own Dockerfile.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages

FROM base AS build-api
RUN uv sync --frozen --no-dev --no-editable --package voizy-api

FROM base AS build-agent
RUN uv sync --frozen --no-dev --no-editable --package voizy-agent
# Make sure the bundled voice-activity model is in place (nothing is fetched at run time).
RUN /app/.venv/bin/python -m voizy_agent download-files

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home voizy
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 10001

FROM runtime AS api
COPY --from=build-api /app/.venv /app/.venv
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
# --proxy-headers makes the client address (login throttling) come from the reverse proxy.
# Trusting any forwarder is only safe because this port is never published: only nginx reaches it.
ENV FORWARDED_ALLOW_IPS="*"
CMD ["uvicorn", "voizy_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM runtime AS agent
COPY --from=build-agent /app/.venv /app/.venv
# The worker writes caches under HOME; the filesystem is otherwise read-only.
ENV HOME=/tmp
CMD ["python", "-m", "voizy_agent", "start"]

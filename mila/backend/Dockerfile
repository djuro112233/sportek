# syntax=docker/dockerfile:1
# MILA API image. Build from the repository root:
#   docker build -f backend/Dockerfile -t mila-api .
#   docker build -f backend/Dockerfile --build-arg EXTRAS=voice,postgres -t mila-api .
#
# The pyproject's setuptools config finds the `app` package under backend/, so `pip install .`
# from the repository root installs MILA and its dependencies. EXTRAS selects optional groups
# from [project.optional-dependencies] (e.g. "voice,postgres"); empty installs the core only.
# The runtime user is non-root, no cache directories are kept, and the container works with a
# read-only root filesystem (compose mounts tmpfs on /tmp for audio uploads).

FROM python:3.11-slim AS runtime

ARG EXTRAS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    MILA_AUDIO_TMP_DIR=/tmp/mila-audio \
    MILA_KB_DIR=/app/kb \
    MILA_MANIFEST_PATH=/app/kb/manifest.yaml

RUN groupadd --system --gid 10001 mila \
    && useradd --system --uid 10001 --gid mila --home-dir /app --shell /usr/sbin/nologin mila

WORKDIR /app

# Dependency layer first (changes rarely): pyproject + the files it references.
COPY pyproject.toml README.md LICENSE ./
COPY backend ./backend
RUN pip install --no-cache-dir --upgrade pip \
    && if [ -n "$EXTRAS" ]; then pip install --no-cache-dir ".[${EXTRAS}]"; else pip install --no-cache-dir "."; fi \
    && find /usr/local/lib/python3.11 -name '__pycache__' -type d -prune -exec rm -rf '{}' + \
    && rm -rf /root/.cache

# Knowledge base (demo sources + manifest) and operational scripts.
COPY kb ./kb
COPY scripts ./scripts
RUN chown -R mila:mila /app

USER mila
EXPOSE 8000

# curl is not in the slim image; urllib keeps the image small.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend", "--no-access-log"]

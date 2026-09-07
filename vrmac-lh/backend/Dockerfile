FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 vrmac
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY seed_data ./seed_data
COPY schemas ./schemas
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data /models && chown -R vrmac:vrmac /data /models /srv
USER vrmac
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
# access log disabled: it would record client IP addresses
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--workers", "1"]

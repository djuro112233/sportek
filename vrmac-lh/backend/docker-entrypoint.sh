#!/bin/sh
# Waits for PostgreSQL, creates the schema + visitor role, loads seed data (idempotent), then runs the command.
set -e
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL"]
for attempt in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("select 1"))
        break
    except Exception as exc:
        print(f"waiting for database ({attempt+1}/60): {exc.__class__.__name__}", flush=True)
        time.sleep(2)
else:
    sys.exit("database not reachable")
PY
# Seeding embeds every approved entry, so the embedding backend has to answer first. With a hosted
# provider (eu_api) or the offline hash provider there is nothing to wait for.
if [ "${EMBEDDINGS_PROVIDER:-ollama}" = "ollama" ] && [ "${SKIP_DB_INIT:-false}" != "true" ]; then
  python - <<'WAITPY'
import os, time, urllib.request

url = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/") + "/api/tags"
for attempt in range(90):
    try:
        urllib.request.urlopen(url, timeout=5)
        print("embedding model server is up", flush=True)
        break
    except Exception as exc:
        print(f"waiting for the model server ({attempt + 1}/90): {exc.__class__.__name__}", flush=True)
        time.sleep(5)
else:
    raise SystemExit(
        "the model server never answered; set EMBEDDINGS_PROVIDER to a hosted provider "
        "or start the local-llm profile"
    )
WAITPY
fi

if [ "${SKIP_DB_INIT:-false}" != "true" ]; then
  python -m app.cli init-db
  python -m app.cli seed
fi
exec "$@"

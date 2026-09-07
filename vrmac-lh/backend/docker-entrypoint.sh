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
if [ "${SKIP_DB_INIT:-false}" != "true" ]; then
  python -m app.cli init-db
  python -m app.cli seed
fi
exec "$@"

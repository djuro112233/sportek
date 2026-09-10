"""Command line entry points.  python -m app.cli <command> [options]"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from .config import settings
from .db import SessionLocal, init_db
from .logging_conf import configure_logging

log = logging.getLogger("vrmac.cli")


def cmd_init_db(args):
    init_db(drop=args.drop)
    print("database initialised (tables, vector extension, visitor role + RLS)")


def cmd_seed(args):
    from .seed.loader import load_seed

    init_db()
    with SessionLocal() as db:
        summary = load_seed(db, reset=args.reset)
    print(json.dumps(summary, indent=2, default=str))


def cmd_reindex(args):
    from .services.indexing import reindex_all_approved

    with SessionLocal() as db:
        n = reindex_all_approved(db)
    print(f"indexed {n} chunks from approved entries")


def cmd_export(args):
    from .services.export import export_all

    with SessionLocal() as db:
        result = export_all(db, out_dir=args.out or settings.export_dir)
    print(json.dumps(result, indent=2, default=str))


def cmd_kpi(args):
    from .services.kpi import compute_kpis

    with SessionLocal() as db:
        result = compute_kpis(db, period_days=args.days, publish=args.publish)
    print(json.dumps(result, indent=2, default=str))


def cmd_kpi_review(args):
    """Disclosure review: publish or reject a computed KPI run."""
    from .services.kpi import review_run

    with SessionLocal() as db:
        result = review_run(db, run_id=args.run_id, decision=args.decision, note=args.note or "")
    print(json.dumps(result, indent=2, default=str))


def cmd_review_sample(args):
    """Monthly human-sampling script: export a review sheet of random answers."""
    from .services.review import export_review_sheet

    with SessionLocal() as db:
        result = export_review_sheet(db, n=args.n, out_dir=args.out or settings.export_dir, days=args.days)
    print(json.dumps(result, indent=2, default=str))


def cmd_stt_eval(args):
    """Measure the speech-to-text word error rate on the Montenegrin sample set."""
    from .services.stt_eval import run_evaluation

    with SessionLocal() as db:
        result = run_evaluation(db)
    print(json.dumps(result, indent=2, default=str))


def cmd_budget(args):
    from .services.budget import status

    with SessionLocal() as db:
        print(json.dumps(status(db), indent=2, default=str))


def cmd_expire_requests(args):
    from .services.requests_lifecycle import expire_stale_requests

    with SessionLocal() as db:
        print(json.dumps(expire_stale_requests(db), indent=2, default=str))


def cmd_kpi_schedule(args):
    """Nightly job: recompute the KPI aggregates at the given UTC hour, forever."""
    from .services.kpi import compute_kpis

    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(hour=args.hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        wait = (nxt - now).total_seconds()
        log.info("next KPI computation at %s (in %.0f s)", nxt.isoformat(), wait)
        time.sleep(wait)
        with SessionLocal() as db:
            compute_kpis(db, period_days=args.days, publish=False)
        try:
            from .services.requests_lifecycle import expire_stale_requests

            with SessionLocal() as db:
                expire_stale_requests(db)
        except ImportError:
            pass


def cmd_grounding_test(args):
    from .services.rag import run_grounding_test

    with SessionLocal() as db:
        result = run_grounding_test(db, questions_path=args.questions, out_path=args.out, lang=args.lang)
    print(json.dumps(result["summary"], indent=2, default=str))
    sys.exit(0 if result["summary"].get("passed") else 1)


def cmd_create_user(args):
    from .auth import hash_password
    from .models import User

    with SessionLocal() as db:
        u = User(
            email=args.email.lower(), password_hash=hash_password(args.password), role=args.role,
            display_name=args.name or args.email.split("@")[0], gender=args.gender,
            # Never true from an administrator's command line: a self-report is something the
            # person does themselves, through POST /api/auth/me/gender. A value set here is
            # recorded but stays out of every gender-disaggregated KPI.
            gender_self_reported=False, is_sample=False,
        )
        db.add(u)
        db.commit()
        print(f"created {u.role} user {u.id}")


def cmd_worker(args):
    from redis import Redis
    from rq import Worker

    from .queue import QUEUE_NAME

    Worker([QUEUE_NAME], connection=Redis.from_url(settings.redis_url)).work()


def cmd_openapi(args):
    from .main import app

    out = args.out or "openapi.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(app.openapi(), fh, indent=2, ensure_ascii=False)
    print(f"wrote {out}")


def main(argv=None):
    configure_logging()
    p = argparse.ArgumentParser(prog="vrmac", description="VRMAC-LH prototype commands")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db"); s.add_argument("--drop", action="store_true"); s.set_defaults(fn=cmd_init_db)
    s = sub.add_parser("seed"); s.add_argument("--reset", action="store_true"); s.set_defaults(fn=cmd_seed)
    s = sub.add_parser("reindex"); s.set_defaults(fn=cmd_reindex)
    s = sub.add_parser("export-ngsi-ld"); s.add_argument("--out"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("kpi-compute"); s.add_argument("--days", type=int, default=365)
    s.add_argument("--publish", action="store_true", help="skip the disclosure review (demo only)"); s.set_defaults(fn=cmd_kpi)
    s = sub.add_parser("kpi-review"); s.add_argument("--run-id", required=True); s.add_argument("--decision", choices=["publish", "reject"], required=True)
    s.add_argument("--note", default=""); s.set_defaults(fn=cmd_kpi_review)
    s = sub.add_parser("review-sample"); s.add_argument("--n", type=int, default=30); s.add_argument("--days", type=int, default=31)
    s.add_argument("--out"); s.set_defaults(fn=cmd_review_sample)
    s = sub.add_parser("stt-eval"); s.set_defaults(fn=cmd_stt_eval)
    s = sub.add_parser("budget"); s.set_defaults(fn=cmd_budget)
    s = sub.add_parser("expire-requests"); s.set_defaults(fn=cmd_expire_requests)
    s = sub.add_parser("kpi-schedule"); s.add_argument("--hour", type=int, default=2); s.add_argument("--days", type=int, default=365); s.set_defaults(fn=cmd_kpi_schedule)
    s = sub.add_parser("grounding-test"); s.add_argument("--questions"); s.add_argument("--out")
    s.add_argument("--lang", choices=["cnr", "en"], help="one launch language (default: all)"); s.set_defaults(fn=cmd_grounding_test)
    s = sub.add_parser("create-user"); s.add_argument("--email", required=True); s.add_argument("--password", required=True)
    s.add_argument("--role", required=True, choices=["host", "ambassador", "validator", "institution"])
    s.add_argument("--gender", choices=["female", "male", "other", "prefer_not_to_say", "undisclosed"],
                   default="undisclosed",
                   help="recorded but NOT counted as a self-report; only the person can report it")
    s.add_argument("--name"); s.set_defaults(fn=cmd_create_user)
    s = sub.add_parser("worker"); s.set_defaults(fn=cmd_worker)
    s = sub.add_parser("openapi"); s.add_argument("--out"); s.set_defaults(fn=cmd_openapi)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

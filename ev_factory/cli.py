from __future__ import annotations

import argparse

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import make_slug


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ev-factory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a new story job")
    p_create.add_argument("--config", default="config.toml")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--date", required=True)

    p_status = sub.add_parser("status", help="show job status")
    p_status.add_argument("--config", default="config.toml")
    p_status.add_argument("--job-id", default=None)
    return parser


def _cmd_create(args) -> int:
    cfg = load_config(args.config)
    slug = make_slug(args.title)
    job_id = f"{args.date}-{slug}"
    folder = JobFolder.create(cfg.jobs_dir, args.date, slug)
    folder.write_json(folder.story_json, {"title": args.title, "date": args.date})
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    repo.create_job(job_id, slug, args.date, cfg.all_languages)
    print(job_id)
    return 0


def _cmd_status(args) -> int:
    cfg = load_config(args.config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    if args.job_id:
        job = repo.get_job(args.job_id)
        if job is None:
            print(f"no such job: {args.job_id}")
            return 1
        print(f"{job['id']}  {job['state']}")
        for lang, status in repo.get_language_statuses(args.job_id).items():
            print(f"  {lang}: {status}")
    else:
        for job in repo.list_jobs():
            print(f"{job['id']}  {job['state']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create":
        return _cmd_create(args)
    if args.command == "status":
        return _cmd_status(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

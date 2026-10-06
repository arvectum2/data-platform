from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from .sync_efficiency import (
    PostgresSyncEfficiencyRunner,
    load_sync_efficiency_suite,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-sync-eval",
        description="Evaluate incremental refresh indexing efficiency.",
    )
    parser.add_argument("suite", type=Path)
    parser.add_argument(
        "--database-url-env",
        default="ARVECTUM_DATA_TEST_DATABASE_URL",
    )
    parser.add_argument("--alembic-config", type=Path, default=Path("alembic.ini"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-pass-rate-below", type=float, default=1.0)
    parser.add_argument("--fail-amplification-above", type=float, default=1.0)
    parser.add_argument("--fail-unnecessary-indexed-above", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.getenv(args.database_url_env, "").strip()
    if not database_url:
        raise SystemExit(f"{args.database_url_env} is not configured")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config(str(args.alembic_config)), "head")
        summary = PostgresSyncEfficiencyRunner(
            database_url=database_url,
            suite=load_sync_efficiency_suite(args.suite),
        ).run()
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    if summary.pass_rate < args.fail_pass_rate_below:
        return 2
    if summary.indexing_amplification > args.fail_amplification_above:
        return 3
    if summary.unnecessary_indexed_resources > args.fail_unnecessary_indexed_above:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

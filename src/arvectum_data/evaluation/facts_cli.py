from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from .facts import PostgresFactRunner, evaluate_fact_chunking, load_fact_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-fact-eval",
        description="Evaluate exact fact chunk preservation and optional PostgreSQL retrieval.",
    )
    parser.add_argument("suite", type=Path)
    parser.add_argument("--chunk-only", action="store_true")
    parser.add_argument(
        "--database-url-env",
        default="ARVECTUM_DATA_TEST_DATABASE_URL",
    )
    parser.add_argument("--alembic-config", type=Path, default=Path("alembic.ini"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-chunk-below", type=float, default=1.0)
    parser.add_argument("--fail-context-below", type=float, default=1.0)
    parser.add_argument("--fail-retrieval-below", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    suite = load_fact_suite(args.suite)

    if args.chunk_only:
        summary = evaluate_fact_chunking(suite)
    else:
        database_url = os.getenv(args.database_url_env, "").strip()
        if not database_url:
            raise SystemExit(f"{args.database_url_env} is not configured")
        previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
        os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
        try:
            command.upgrade(Config(str(args.alembic_config)), "head")
            summary = PostgresFactRunner(
                database_url=database_url,
                suite=suite,
            ).evaluate()
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

    if summary.chunk_preservation_rate < args.fail_chunk_below:
        return 2
    if summary.context_preservation_rate < args.fail_context_below:
        return 3
    if not args.chunk_only:
        if (
            summary.retrieval_top1_rate is None
            or summary.retrieval_top1_rate < args.fail_retrieval_below
        ):
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

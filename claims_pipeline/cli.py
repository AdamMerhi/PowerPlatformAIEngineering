"""CLI entrypoint: python -m claims_pipeline {extract|transform|load|run} [--dry-run] [--refresh]

This is the single code path that the Airflow DAG, GitHub Actions, and
a human on the command line all call -- there is no separate "prod"
implementation.
"""
from __future__ import annotations

import argparse
import logging
import sys

from claims_pipeline.config import ROW_CAP, PipelineConfig, SnowflakeConfig
from claims_pipeline.extract import extract_data_car
from claims_pipeline.load import load_dry_run, load_to_snowflake
from claims_pipeline.transform import transform

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run(*, dry_run: bool, refresh: bool, row_cap: int = ROW_CAP) -> None:
    cfg = PipelineConfig(row_cap=row_cap, dry_run=dry_run)
    cache_dir = cfg.ensure_cache_dir()

    raw = extract_data_car(cache_dir=cache_dir, refresh=refresh)
    transformed = transform(raw, row_cap=cfg.row_cap)

    if dry_run:
        out_path = load_dry_run(transformed, cache_dir=cache_dir)
        logger.info("dry run complete: %s (%d rows)", out_path, len(transformed))
        return

    sf_config = SnowflakeConfig.from_env()
    stats = load_to_snowflake(transformed, config=sf_config)
    logger.info("load complete: %s", stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="extract, transform, and load in one shot")
    run_parser.add_argument("--dry-run", action="store_true", help="write Parquet instead of loading to Snowflake")
    run_parser.add_argument("--refresh", action="store_true", help="force re-download of the source tarball")
    run_parser.add_argument("--row-cap", type=int, default=ROW_CAP)

    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            run(dry_run=args.dry_run, refresh=args.refresh, row_cap=args.row_cap)
        except KeyError as missing:
            print(f"missing env var: {missing}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

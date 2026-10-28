"""DAG C: daily ingest of Australian motor claims into Snowflake.

This DAG is intentionally thin -- every task is a few lines calling
into `claims_pipeline`, which is plain importable Python with its own
unit tests (tests/test_transform.py). That split exists because
Airflow doesn't run natively on Windows (this repo's dev machine): the
pipeline logic can be developed and tested locally without a running
Airflow instance, while this file only needs to parse correctly
(tests/test_dag_integrity.py) and is exercised for real on the Linux
GitHub Actions runner and in production.

XCom carries only file paths between tasks, never DataFrames -- those
can be large and don't belong in Airflow's metadata database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

default_args = {
    "owner": "claims-poc",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="motor_claims_ingest",
    description="Extract dataCar (AU motor claims) -> transform -> load to Snowflake -> dbt build",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["claims-poc", "dag-c", "snowflake"],
)
def motor_claims_ingest():
    @task
    def extract(refresh: bool = False) -> str:
        from claims_pipeline.config import CACHE_DIR
        from claims_pipeline.extract import extract_data_car

        df = extract_data_car(cache_dir=CACHE_DIR, refresh=refresh)
        path = CACHE_DIR / "dataCar_extracted.parquet"
        df.to_parquet(path, index=False)
        return str(path)

    @task
    def transform_task(extracted_path: str) -> str:
        import pandas as pd

        from claims_pipeline.config import CACHE_DIR, ROW_CAP
        from claims_pipeline.transform import transform

        df = pd.read_parquet(extracted_path)
        transformed = transform(df, row_cap=ROW_CAP)
        path = CACHE_DIR / "motor_claims_transformed.parquet"
        transformed.to_parquet(path, index=False)
        return str(path)

    @task
    def load_task(transformed_path: str) -> dict:
        import pandas as pd

        from claims_pipeline.config import SnowflakeConfig
        from claims_pipeline.load import TARGET_COLUMNS, load_to_snowflake

        df = pd.read_parquet(transformed_path)[TARGET_COLUMNS]
        config = SnowflakeConfig.from_env()
        return load_to_snowflake(df, config=config)

    @task
    def dbt_build(load_stats: dict) -> None:
        import subprocess

        logger.info("load stats: %s", load_stats)
        result = subprocess.run(
            ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
            check=False,
            capture_output=True,
            text=True,
        )
        logger.info(result.stdout)
        if result.returncode != 0:
            logger.error(result.stderr)
            raise RuntimeError("dbt build failed -- see logs above")

    extracted = extract()
    transformed = transform_task(extracted)
    load_stats = load_task(transformed)
    dbt_build(load_stats)


motor_claims_ingest()

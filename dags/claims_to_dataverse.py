"""DAG D: sync the specialist claim queue from Snowflake CURATED to Dataverse.

Thin on purpose, like DAG C: the logic lives in `claims_pipeline.dataverse`
(OAuth client credentials, upsert by source row id). Decision columns owned by
the canvas app are never overwritten by this sync.

Runs after DAG C (which ends with dbt build) so the queue view is fresh.
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
    dag_id="claims_to_dataverse",
    description="Snowflake CURATED.V_CLAIM_QUEUE -> Dataverse Claim table (REST + OAuth)",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["claims-poc", "dag-d", "dataverse"],
)
def claims_to_dataverse():
    @task
    def ensure_table() -> str:
        from claims_pipeline.dataverse import DataverseClient, DataverseConfig

        return DataverseClient(DataverseConfig.from_env()).ensure_table()

    @task
    def sync_queue(entity_set: str) -> dict:
        from claims_pipeline.dataverse import (
            DataverseClient,
            DataverseConfig,
            read_queue,
        )

        rows = read_queue()
        stats = DataverseClient(DataverseConfig.from_env()).upsert_claims(rows)
        logger.info("synced %s into %s: %s", len(rows), entity_set, stats)
        return stats

    sync_queue(ensure_table())


claims_to_dataverse()

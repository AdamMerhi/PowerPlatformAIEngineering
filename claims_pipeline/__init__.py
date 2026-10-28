"""Motor claims ingest pipeline (DAG C).

Pulls the Australian `dataCar` dataset (CRAN package `insuranceData`),
derives policy/loss dates deterministically, and loads it into
Snowflake `CLAIMS_POC.RAW.MOTOR_CLAIMS_RAW`. All business logic lives
here as plain, importable Python so it can be exercised from pytest,
from the Airflow DAG in `dags/motor_claims_ingest.py`, or from the
GitHub Actions workflow — without needing an Airflow server running
locally.
"""

from claims_pipeline.config import PipelineConfig

__all__ = ["PipelineConfig"]

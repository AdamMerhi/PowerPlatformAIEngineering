"""Load transformed motor-claims rows into Snowflake RAW.MOTOR_CLAIMS_RAW.

Writes to a transient staging table then MERGEs on src_row_id, so a
daily re-run re-asserts rows rather than duplicating them. This is the
one correctness property that matters most for an idempotent daily
pipeline -- see tests/test_transform.py for the determinism tests that
make the MERGE key safe to rely on, and the plan's verification step
that runs the load twice and checks the row count doesn't move.

`--dry-run` (load_dry_run) skips Snowflake entirely and writes Parquet
to .cache/, so extract+transform stay testable before a Snowflake
account exists.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from claims_pipeline.config import SnowflakeConfig

logger = logging.getLogger(__name__)

STAGING_TABLE = "MOTOR_CLAIMS_STG"
TARGET_TABLE = "MOTOR_CLAIMS_RAW"

TARGET_COLUMNS = [
    "src_row_id",
    "veh_value",
    "exposure",
    "clm",
    "numclaims",
    "claimcst0",
    "veh_body",
    "veh_age",
    "gender",
    "area",
    "agecat",
    "policy_start_date",
    "policy_end_date",
    "loss_date",
    "source_system",
    "ingested_at",
]


def load_dry_run(df: pd.DataFrame, *, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / "motor_claims_transformed.parquet"
    df[TARGET_COLUMNS].to_parquet(out_path, index=False)
    logger.info("dry-run: wrote %d rows to %s", len(df), out_path)
    return out_path


def _merge_sql(database: str, schema: str) -> str:
    update_cols = [c for c in TARGET_COLUMNS if c != "src_row_id"]
    update_clause = ", ".join(f"t.{c} = s.{c}" for c in update_cols)
    insert_cols = ", ".join(TARGET_COLUMNS)
    insert_vals = ", ".join(f"s.{c}" for c in TARGET_COLUMNS)
    return f"""
        MERGE INTO {database}.{schema}.{TARGET_TABLE} t
        USING {database}.{schema}.{STAGING_TABLE} s
          ON t.src_row_id = s.src_row_id
        WHEN MATCHED THEN UPDATE SET {update_clause}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """


def load_to_snowflake(df: pd.DataFrame, *, config: SnowflakeConfig) -> dict:
    """Write df to Snowflake via a staging table + MERGE. Returns MERGE stats."""
    import snowflake.connector
    from snowflake.connector.pandas_tools import write_pandas

    conn = snowflake.connector.connect(**config.connect_kwargs())
    try:
        cur = conn.cursor()
        cur.execute(f"USE DATABASE {config.database}")
        cur.execute(f"USE SCHEMA {config.schema}")

        cur.execute(
            f"CREATE TEMPORARY TABLE {STAGING_TABLE} LIKE {TARGET_TABLE}"
        )
        success, nchunks, nrows, _ = write_pandas(
            conn,
            df[TARGET_COLUMNS],
            STAGING_TABLE.upper(),
            auto_create_table=False,
            quote_identifiers=False,
            use_logical_type=True,
        )
        if not success:
            raise RuntimeError(f"write_pandas failed to stage {nrows} rows")
        logger.info("staged %d rows in %d chunk(s)", nrows, nchunks)

        merge_result = cur.execute(_merge_sql(config.database, config.schema)).fetchone()
        inserted, updated = (merge_result[0], merge_result[1]) if merge_result else (0, 0)
        logger.info("merge complete: inserted=%d updated=%d", inserted, updated)

        conn.commit()
        return {"inserted": inserted, "updated": updated, "staged": nrows}
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        except Exception:
            logger.warning("could not drop staging table %s", STAGING_TABLE, exc_info=True)
        conn.close()

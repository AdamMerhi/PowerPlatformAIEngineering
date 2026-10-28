"""Transform raw dataCar rows into the shape loaded into RAW.MOTOR_CLAIMS_RAW.

dataCar carries no date fields -- it's anonymised and aggregated to one
row per policy. Both the "newest to oldest" ordering and the dbt date
tests need real dates to work with, so this module derives them
deterministically from a hash of each row's own data:

    src_row_id        = sha256(all source columns || row index)
    policy_start_date = 2004-01-01 + (hash_a % 730) days
    policy_end_date   = policy_start_date + 365 days
    loss_date         = policy_start_date + (hash_b % exposure_days) days,
                         only when clm == 1; else NULL
    ingested_at       = a single run timestamp, same for every row

This is clearly a derivation, not source truth, and is documented as
such in dbt/models/staging/stg_motor_claims.yml. The row index is
included in the hash input because dataCar contains genuine duplicate
rows (distinct anonymous policies with identical attribute values) --
hashing attributes alone would collapse those into one key and break
the uniqueness test downstream.

Row ordering ("newest to oldest") and the ROW_CAP safety guard are
both applied here, once, so every caller (CLI, Airflow task, tests)
sees the same final row set.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

import pandas as pd

from claims_pipeline.config import POLICY_WINDOW_SPAN_DAYS, ROW_CAP

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = "CRAN:insuranceData:dataCar"
POLICY_WINDOW_START = datetime(2004, 1, 1, tzinfo=UTC)
POLICY_TERM_DAYS = 365

SOURCE_COLUMNS = [
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
]


def _row_hash(row: pd.Series, row_index: int) -> str:
    """Stable sha256 over every source column plus the row's position."""
    parts = [str(row[c]) for c in SOURCE_COLUMNS]
    parts.append(str(row_index))
    digest_input = "|".join(parts).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def _hash_to_int(src_row_id: str, salt: str) -> int:
    """Derive a second, independent integer digest from src_row_id.

    Using src_row_id (rather than re-hashing the raw row) keeps the
    whole derivation traceable to a single key, and the salt keeps
    policy_start_date and loss_date independent of each other.
    """
    h = hashlib.sha256((src_row_id + salt).encode("utf-8")).hexdigest()
    return int(h, 16)


def _derive_dates(src_row_id: str, exposure: float, clm: int) -> tuple:
    h1 = _hash_to_int(src_row_id, "policy_start")
    h2 = _hash_to_int(src_row_id, "loss_date")

    policy_start_date = POLICY_WINDOW_START + timedelta(days=h1 % POLICY_WINDOW_SPAN_DAYS)
    policy_end_date = policy_start_date + timedelta(days=POLICY_TERM_DAYS)

    loss_date = None
    if clm == 1:
        exposure_days = max(1, int(exposure * POLICY_TERM_DAYS))
        loss_date = policy_start_date + timedelta(days=h2 % exposure_days)

    return policy_start_date.date(), policy_end_date.date(), (loss_date.date() if loss_date else None)


def transform(df: pd.DataFrame, *, row_cap: int = ROW_CAP, run_ts: datetime | None = None) -> pd.DataFrame:
    """Add derived keys/dates, sort newest-to-oldest, and apply the row cap.

    `run_ts` is injectable for deterministic tests; defaults to "now".
    """
    if run_ts is None:
        run_ts = datetime.now(UTC)

    out = df.copy()
    out["clm"] = out["clm"].astype(int)
    out["numclaims"] = out["numclaims"].astype(int)
    out["veh_age"] = out["veh_age"].astype(int)
    out["agecat"] = out["agecat"].astype(int)

    src_row_ids = [
        _row_hash(row, idx) for idx, row in out.reset_index(drop=True).iterrows()
    ]
    out["src_row_id"] = src_row_ids

    derived = [
        _derive_dates(src_row_id, row["exposure"], row["clm"])
        for src_row_id, (_, row) in zip(src_row_ids, out.iterrows())
    ]
    out["policy_start_date"] = [d[0] for d in derived]
    out["policy_end_date"] = [d[1] for d in derived]
    out["loss_date"] = [d[2] for d in derived]

    out["source_system"] = SOURCE_SYSTEM
    # Stored naive (tz stripped) because RAW.MOTOR_CLAIMS_RAW.INGESTED_AT is
    # TIMESTAMP_NTZ: Snowflake's write_pandas (use_logical_type=True)
    # reinterprets a tz-aware timestamp against the session's local
    # timezone before truncating it into an NTZ column, which silently
    # shifts the stored wall-clock value by the session UTC offset.
    # Writing an already-naive UTC value sidesteps that conversion.
    out["ingested_at"] = run_ts.astimezone(UTC).replace(tzinfo=None)

    # Sort newest to oldest on the derived recency signal: loss_date
    # when there is one, else the policy's own start date.
    out["_sort_key"] = out["loss_date"].fillna(out["policy_start_date"])
    out = out.sort_values("_sort_key", ascending=False).drop(columns=["_sort_key"])
    out = out.reset_index(drop=True)

    if len(out) > row_cap:
        logger.warning("row cap bound: %d rows truncated to %d", len(out), row_cap)
        out = out.head(row_cap)
    else:
        logger.info("row cap did not bind: %d rows <= cap of %d", len(out), row_cap)

    return out.reset_index(drop=True)

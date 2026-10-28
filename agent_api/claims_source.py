"""Build the facts the agent reasons over, from a Dataverse claim or a Snowflake row.

The API reads the claim itself by id, so a caller cannot hand the agent different facts.
"""
from __future__ import annotations

import re
from decimal import Decimal

from agent_api.schemas import ClaimFacts
from claims_pipeline.dataverse import DataverseClient, display_value

CLAIM_ID = re.compile(r"[0-9a-f]{64}")  # the source row id (SHA-256 hex); validated before use in a filter


def _facts(claim_id: str, body, gender, band, agecat, veh_value, exposure, numclaims, amount, start, end, loss) -> ClaimFacts:
    value_dollars = float(veh_value or 0) * 10_000  # source value is recorded in units of $10,000 (clause 4.3)
    amount = float(amount)
    return ClaimFacts(
        claim_id=claim_id, vehicle_body=str(body), gender=str(gender), driver_age_band=str(band),
        age_category=int(agecat), vehicle_value_dollars=value_dollars, exposure=float(exposure),
        number_of_claims=int(numclaims), claim_amount=amount,
        claim_pct_of_vehicle_value=(amount / value_dollars * 100) if value_dollars > 0 else None,
        loss_date=str(loss)[:10], policy_start=str(start)[:10], policy_end=str(end)[:10],
    )


def facts_from_snowflake(row: dict) -> ClaimFacts:
    """A row of CURATED.V_CLAIM_ASSESSMENT (raw codes, upper-case column names)."""
    return _facts(
        row["SRC_ROW_ID"], display_value("vehbody", row["VEH_BODY"]), display_value("gender", row["GENDER"]),
        display_value("driverageband", row["DRIVER_AGE_BAND"]), row["AGECAT"],
        Decimal(row["VEH_VALUE"] or 0), row["EXPOSURE"], row["NUMCLAIMS"], row["CLAIM_AMOUNT"],
        row["POLICY_START_DATE"], row["POLICY_END_DATE"], row["LOSS_DATE"],
    )


def facts_from_dataverse(record: dict, prefix: str) -> ClaimFacts:
    g = lambda s: record.get(f"{prefix}_{s}")
    return _facts(
        g("srcrowid"), g("vehbody"), g("gender"), g("driverageband"), g("agecat"), g("vehvalue"),
        g("exposure"), g("numclaims"), g("claimamount"), g("policystartdate"), g("policyenddate"), g("lossdate"),
    )


def fetch_facts(client: DataverseClient, claim_id: str) -> ClaimFacts:
    if not CLAIM_ID.fullmatch(claim_id):
        raise ValueError("claim_id must be the 64-character source row id")
    p = client.prefix
    columns = ",".join(f"{p}_{s}" for s in (
        "srcrowid", "vehbody", "gender", "driverageband", "agecat", "vehvalue", "exposure", "numclaims",
        "claimamount", "policystartdate", "policyenddate", "lossdate"))
    entity_set = client.entity_set()
    rows = client._request("GET", f"/{entity_set}?$select={columns}&$filter={p}_srcrowid eq '{claim_id}'&$top=1")
    records = rows.json().get("value", [])
    if not records:
        raise LookupError(f"claim {claim_id[:8]} not found")
    return facts_from_dataverse(records[0], p)

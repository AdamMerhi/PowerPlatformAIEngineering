from datetime import date
from decimal import Decimal

import pytest

from claims_pipeline.dataverse import (
    APP_COLUMNS,
    SOURCE_COLUMNS,
    attribute_metadata,
    to_record,
)


def _row():
    return {
        "SRC_ROW_ID": "abc", "VEH_BODY": "UTE", "GENDER": "F", "AGECAT": 3, "DRIVER_AGE_BAND": "mid",
        "VEH_VALUE": Decimal("3.08"), "EXPOSURE": Decimal("0.9637"), "NUMCLAIMS": 1,
        "CLAIM_AMOUNT": Decimal("2404.24"), "POLICY_START_DATE": date(2005, 6, 28),
        "POLICY_END_DATE": date(2006, 6, 28), "LOSS_DATE": date(2006, 2, 20),
        "RECOMMENDED_OUTCOME": "ACCEPT", "CITED_CLAUSES": None, "CONDITIONS": None,
    }


def test_to_record_prefixes_and_converts_types():
    record = to_record(_row(), "cr123")
    assert record["cr123_srcrowid"] == "abc"
    assert record["cr123_claimamount"] == 2404.24
    assert record["cr123_lossdate"] == "2006-02-20"
    assert record["cr123_agecat"] == 3
    assert record["cr123_citedclauses"] is None


def test_to_record_never_sends_app_owned_columns():
    record = to_record(_row(), "cr123")
    for suffix, _ in APP_COLUMNS:
        assert f"cr123_{suffix}" not in record


def test_every_source_column_has_attribute_metadata():
    for _, suffix, kind in SOURCE_COLUMNS:
        assert attribute_metadata(f"cr123_{suffix}", suffix, kind)["SchemaName"] == f"cr123_{suffix}"


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        attribute_metadata("cr123_x", "x", "blob")

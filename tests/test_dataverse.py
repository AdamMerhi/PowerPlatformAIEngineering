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


def test_to_record_uses_readable_values():
    row = {**_row(), "VEH_BODY": "STNWG", "GENDER": "F", "DRIVER_AGE_BAND": "mid"}
    record = to_record(row, "cr123")
    assert record["cr123_vehbody"] == "Station wagon"
    assert record["cr123_gender"] == "Female"
    assert record["cr123_driverageband"] == "Mid"


def test_unknown_vehicle_code_falls_back_to_title_case():
    assert to_record({**_row(), "VEH_BODY": "WEIRD"}, "cr123")["cr123_vehbody"] == "Weird"


def test_to_record_never_sends_app_owned_columns():
    record = to_record(_row(), "cr123")
    for suffix, _ in APP_COLUMNS:
        assert f"cr123_{suffix}" not in record


def test_every_source_column_has_attribute_metadata():
    for _, suffix, kind in SOURCE_COLUMNS:
        assert attribute_metadata(f"cr123_{suffix}", suffix, kind)["SchemaName"] == f"cr123_{suffix}"


def test_agent_tables_have_labels_and_valid_column_kinds():
    from claims_pipeline.dataverse import AGENT_TABLES, ATTRIBUTE_TYPES, LABELS

    for _display, _plural, _description, primary, columns in AGENT_TABLES.values():
        assert primary in LABELS
        for suffix, kind in columns:
            assert suffix in LABELS and kind in ATTRIBUTE_TYPES
            assert attribute_metadata(f"cr123_{suffix}", LABELS[suffix], kind)["SchemaName"] == f"cr123_{suffix}"


def test_boolean_columns_carry_yes_no_options():
    meta = attribute_metadata("cr123_agrees", "Agrees", "bool")
    assert meta["OptionSet"]["TrueOption"]["Value"] == 1 and meta["OptionSet"]["FalseOption"]["Value"] == 0


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        attribute_metadata("cr123_x", "x", "blob")

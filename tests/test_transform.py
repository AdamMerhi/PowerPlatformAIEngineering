from datetime import UTC, date, datetime

import pandas as pd
import pytest

from claims_pipeline.transform import POLICY_WINDOW_START, SOURCE_COLUMNS, transform


def _sample_df(n: int = 20, duplicate_last_two: bool = False) -> pd.DataFrame:
    rows = []
    for i in range(n):
        has_claim = i % 3 == 0  # every third row has a claim
        rows.append(
            {
                "veh_value": 1.0 + i,
                "exposure": 0.1 + (i % 10) / 10,
                "clm": 1 if has_claim else 0,
                "numclaims": 1 if has_claim else 0,
                "claimcst0": 500.0 * (i + 1) if has_claim else 0.0,
                "veh_body": "SEDAN",
                "veh_age": (i % 4) + 1,
                "gender": "F" if i % 2 == 0 else "M",
                "area": "A",
                "agecat": (i % 6) + 1,
            }
        )
    df = pd.DataFrame(rows)
    if duplicate_last_two:
        # dataCar genuinely contains duplicate attribute rows for
        # distinct anonymous policies -- make the last row identical
        # to the first to exercise that case.
        df.iloc[-1] = df.iloc[0]
    return df


def test_determinism_same_input_same_output():
    df = _sample_df()
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)

    out1 = transform(df, run_ts=run_ts)
    out2 = transform(df, run_ts=run_ts)

    pd.testing.assert_frame_equal(
        out1.sort_values("src_row_id").reset_index(drop=True),
        out2.sort_values("src_row_id").reset_index(drop=True),
    )


def test_loss_date_null_iff_no_claim():
    df = _sample_df()
    out = transform(df)

    claim_rows = out[out["clm"] == 1]
    no_claim_rows = out[out["clm"] == 0]

    assert (claim_rows["loss_date"].notna()).all()
    assert (no_claim_rows["loss_date"].isna()).all()


def test_loss_date_within_policy_term():
    df = _sample_df()
    out = transform(df)

    with_loss = out[out["loss_date"].notna()]
    assert (with_loss["loss_date"] >= with_loss["policy_start_date"]).all()
    assert (with_loss["loss_date"] <= with_loss["policy_end_date"]).all()


def test_policy_dates_within_source_window():
    df = _sample_df()
    out = transform(df)

    window_start = POLICY_WINDOW_START.date()
    window_end = date(2005, 12, 31)
    assert (out["policy_start_date"] >= window_start).all()
    assert (out["policy_start_date"] <= window_end).all()
    assert (out["policy_end_date"] > out["policy_start_date"]).all()


def test_row_cap_is_applied():
    df = _sample_df(n=50)
    out = transform(df, row_cap=10)
    assert len(out) == 10


def test_row_cap_does_not_bind_when_under_limit():
    df = _sample_df(n=50)
    out = transform(df, row_cap=100_000)
    assert len(out) == 50


def test_duplicate_source_rows_get_distinct_keys():
    df = _sample_df(duplicate_last_two=True)
    out = transform(df)

    assert out["src_row_id"].is_unique
    assert len(out) == len(df)


def test_sorted_newest_to_oldest():
    df = _sample_df()
    out = transform(df)

    sort_key = out["loss_date"].fillna(out["policy_start_date"])
    assert list(sort_key) == sorted(sort_key, reverse=True)


def test_source_columns_constant_matches_expected_fields():
    # guards against SOURCE_COLUMNS drifting out of sync with the
    # columns extract.py actually produces.
    expected = {
        "veh_value", "exposure", "clm", "numclaims", "claimcst0",
        "veh_body", "veh_age", "gender", "area", "agecat",
    }
    assert set(SOURCE_COLUMNS) == expected


def test_missing_source_column_raises():
    df = _sample_df().drop(columns=["gender"])
    with pytest.raises(KeyError):
        transform(df)

"""Extract `dataCar` from the CRAN `insuranceData` package tarball.

`dataCar` is a real Australian third-party motor insurance dataset
(67,856 one-year policies taken out in 2004 or 2005). It ships only as
an R `.rda` inside the package source tarball on CRAN -- there is no
plain CSV -- so this module downloads the tarball, extracts the `.rda`
member, and reads it with `pyreadr` (pure Python, no R runtime needed).

The tarball is cached under `.cache/` so repeated runs (and repeated
pytest invocations) don't hit the network every time; pass
`refresh=True` to force a re-download.
"""
from __future__ import annotations

import hashlib
import logging
import tarfile
from pathlib import Path

import pandas as pd
import requests

from claims_pipeline.config import CACHE_DIR, CRAN_TARBALL_URL, RDA_MEMBER_PATH

logger = logging.getLogger(__name__)

# Columns present in dataCar as documented by the insuranceData package,
# minus the constant junk factor `_OBSTAT_` which we drop on read.
EXPECTED_COLUMNS = {
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
}
MIN_EXPECTED_ROWS = 60_000  # real row count is 67,856; guard against a truncated/corrupt pull


class ExtractError(RuntimeError):
    """Raised when the source data doesn't look like dataCar."""


def _download_tarball(dest: Path, *, refresh: bool = False) -> Path:
    if dest.exists() and not refresh:
        logger.info("using cached tarball %s", dest)
        return dest
    logger.info("downloading %s", CRAN_TARBALL_URL)
    resp = requests.get(CRAN_TARBALL_URL, timeout=60)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _read_rda_member(tarball: Path) -> pd.DataFrame:
    import pyreadr

    with tarfile.open(tarball, "r:gz") as tf:
        try:
            member = tf.getmember(RDA_MEMBER_PATH)
        except KeyError as exc:
            raise ExtractError(
                f"{RDA_MEMBER_PATH} not found in {tarball} -- package layout changed?"
            ) from exc
        extracted = tf.extractfile(member)
        if extracted is None:
            raise ExtractError(f"could not extract {RDA_MEMBER_PATH}")
        raw_bytes = extracted.read()

    # pyreadr reads from a path, not a file-like object -- write the
    # member out to a temp file next to the cache dir.
    tmp_path = tarball.parent / "dataCar.rda"
    tmp_path.write_bytes(raw_bytes)
    try:
        result = pyreadr.read_r(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    # dataCar.rda contains a single object named "dataCar".
    if "dataCar" not in result:
        raise ExtractError(
            f"expected object 'dataCar' in {RDA_MEMBER_PATH}, found {list(result)}"
        )
    return result["dataCar"]


def extract_data_car(*, cache_dir: Path = CACHE_DIR, refresh: bool = False) -> pd.DataFrame:
    """Download (if needed) and parse dataCar. Returns a validated DataFrame."""
    tarball = _download_tarball(cache_dir / "insuranceData.tar.gz", refresh=refresh)
    logger.info("tarball sha256=%s", _sha256(tarball))

    df = _read_rda_member(tarball)
    df.columns = [c.lower() for c in df.columns]
    # _OBSTAT_ is a constant junk factor in dataCar; drop it if present.
    if "_obstat_" in df.columns:
        df = df.drop(columns=["_obstat_"])

    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ExtractError(f"dataCar is missing expected columns: {sorted(missing)}")
    if len(df) < MIN_EXPECTED_ROWS:
        raise ExtractError(
            f"dataCar has only {len(df)} rows, expected >= {MIN_EXPECTED_ROWS} "
            "-- source may be truncated or corrupt"
        )

    df = df.reset_index(drop=True)
    logger.info("extracted dataCar: %d rows, %d columns", len(df), len(df.columns))
    return df

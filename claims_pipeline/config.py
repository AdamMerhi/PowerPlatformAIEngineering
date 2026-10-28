"""Environment/config loading for the motor claims pipeline.

Credentials come from environment variables only (never hard-coded,
never committed) — consistent with CLAUDE.md. The Snowflake key-pair
auth block mirrors `scripts/check_snowflake.py` exactly so there is
one auth code path in the repo, not two.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Safety guard on row volume. dataCar has 67,856 rows, so in practice
# this never binds -- it exists so a future, larger source can't
# silently blow out the table or the warehouse bill.
ROW_CAP = 100_000

# dataCar is "one-year vehicle insurance policies taken out in 2004 or
# 2005" (insuranceData package docs). Derived dates are seeded inside
# this real window -- see transform.py for how.
POLICY_WINDOW_START = "2004-01-01"
POLICY_WINDOW_SPAN_DAYS = 730  # 2004-01-01 .. 2005-12-31 inclusive-ish

CRAN_TARBALL_URL = (
    "https://cran.r-project.org/src/contrib/insuranceData_1.0.tar.gz"
)
RDA_MEMBER_PATH = "insuranceData/data/dataCar.rda"

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache"


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    schema: str
    private_key_path: str | None
    password: str | None

    @classmethod
    def from_env(cls) -> SnowflakeConfig:
        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ.get("SNOWFLAKE_USER", "POC_SVC"),
            role=os.environ.get("SNOWFLAKE_ROLE", "POC_ROLE"),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CLAIMS_WH"),
            database=os.environ.get("SNOWFLAKE_DATABASE", "CLAIMS_POC"),
            schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
            private_key_path=os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"),
            password=os.environ.get("SNOWFLAKE_PASSWORD"),
        )

    def connect_kwargs(self) -> dict:
        """Build snowflake.connector.connect() kwargs.

        Mirrors scripts/check_snowflake.py:connect() -- key-pair auth
        when SNOWFLAKE_PRIVATE_KEY_PATH is set, password fallback
        otherwise. Import of `cryptography` is local so this module
        can be imported (e.g. for --dry-run) without it installed.
        """
        args: dict = {
            "account": self.account,
            "user": self.user,
            "role": self.role,
            "warehouse": self.warehouse,
            "database": self.database,
        }
        if self.private_key_path:
            from cryptography.hazmat.primitives import serialization

            with open(self.private_key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            args["private_key"] = key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        else:
            if not self.password:
                raise KeyError("SNOWFLAKE_PASSWORD")
            args["password"] = self.password
        return args


@dataclass(frozen=True)
class PipelineConfig:
    row_cap: int = ROW_CAP
    cache_dir: Path = field(default_factory=lambda: CACHE_DIR)
    dry_run: bool = False

    def ensure_cache_dir(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

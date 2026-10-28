"""Read-only Snowflake connectivity check. Reads credentials from env vars only.

Requires: pip install snowflake-connector-python cryptography
"""
import os
import sys

import snowflake.connector
from cryptography.hazmat.primitives import serialization


def connect():
    args = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        role=os.environ.get("SNOWFLAKE_ROLE", "POC_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CLAIMS_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "CLAIMS_POC"),
    )
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        args["private_key"] = key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    else:
        args["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    return snowflake.connector.connect(**args)


def main():
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
        print("connected as:", cur.fetchone())
        for table in ("RAW.CLAIMS_RAW", "CURATED.PDS_CHUNKS", "CURATED.CLAIM_ASSESSMENTS", "CURATED.DAG_RUN_LOG"):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"{table}: {cur.fetchone()[0]} rows")
            except Exception as exc:  # table may not exist yet
                print(f"{table}: unavailable ({exc.__class__.__name__})")


if __name__ == "__main__":
    try:
        main()
    except KeyError as missing:
        sys.exit(f"missing env var: {missing}")

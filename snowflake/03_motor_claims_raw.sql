-- DAG C: Australian motor claims (dataCar, CRAN insuranceData package).
-- Run as POC_ROLE, after 00_bootstrap.sql. This table is distinct from
-- RAW.CLAIMS_RAW / CURATED.CLAIM_RISK (01_tables_and_seed.sql,
-- 02_dag.sql) -- those hold synthetic data driven by Snowflake native
-- tasks; this one holds real public data loaded by claims_pipeline and
-- transformed by dbt (see dbt/), so the two pipelines can't collide.
USE ROLE POC_ROLE;
USE WAREHOUSE CLAIMS_WH;
USE DATABASE CLAIMS_POC;

CREATE TABLE IF NOT EXISTS RAW.MOTOR_CLAIMS_RAW (
  SRC_ROW_ID        STRING        NOT NULL,  -- sha256 of source cols + row index; MERGE key
  VEH_VALUE         NUMBER(10,2),             -- vehicle value, $10,000s
  EXPOSURE          FLOAT,                    -- fraction of the policy year covered, 0-1
  CLM               NUMBER(1,0),              -- 1 if a claim occurred, else 0
  NUMCLAIMS         NUMBER(3,0),
  CLAIMCST0         NUMBER(12,2),             -- claim cost, 0 if no claim
  VEH_BODY          STRING,
  VEH_AGE           NUMBER(1,0),              -- 1 (youngest) .. 4
  GENDER            STRING,                   -- F / M
  AREA              STRING,                   -- A .. F
  AGECAT            NUMBER(1,0),              -- 1 (youngest) .. 6
  -- Derived (dataCar ships with no date fields) -- see
  -- claims_pipeline/transform.py and dbt/models/staging/stg_motor_claims.yml.
  POLICY_START_DATE DATE,
  POLICY_END_DATE   DATE,
  LOSS_DATE         DATE,                     -- NULL when CLM = 0
  SOURCE_SYSTEM     STRING        DEFAULT 'CRAN:insuranceData:dataCar',
  INGESTED_AT       TIMESTAMP_NTZ,
  CONSTRAINT PK_MOTOR_CLAIMS_RAW PRIMARY KEY (SRC_ROW_ID)
);

-- Grants are explicit (not FUTURE) to match 00_bootstrap.sql's style;
-- POC_ROLE already owns the schema via "GRANT ALL ON ALL SCHEMAS", so
-- this is belt-and-braces for anyone granted narrower access later.
GRANT ALL ON TABLE RAW.MOTOR_CLAIMS_RAW TO ROLE POC_ROLE;

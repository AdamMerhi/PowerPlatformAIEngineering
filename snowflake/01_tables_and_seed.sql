-- Claims PDS Agent schema. Synthetic data only. Run as POC_ROLE.
-- Source PDS: Zurich Business Insurance Motor PDS (public document), chunked and sparse-embedded by Airflow DAG A.
USE ROLE POC_ROLE;
USE WAREHOUSE CLAIMS_WH;
USE DATABASE CLAIMS_POC;

-- RAW: landing tables, loaded as-is
CREATE OR REPLACE TABLE RAW.POLICIES_RAW (
  POLICY_NUMBER STRING, HOLDER_NAME STRING, PRODUCT STRING,
  START_DATE DATE, SUM_INSURED NUMBER(12,2), INGESTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE RAW.CLAIMS_RAW (
  CLAIM_ID STRING, POLICY_NUMBER STRING, LOSS_DATE DATE, LOSS_TYPE STRING,
  NARRATIVE STRING, CLAIMED_AMOUNT NUMBER(12,2), REPORTED_AT TIMESTAMP_NTZ,
  INGESTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- CLEAN: typed, de-duplicated
CREATE OR REPLACE TABLE CLEAN.POLICIES (
  POLICY_NUMBER STRING, PRODUCT STRING, START_DATE DATE, SUM_INSURED NUMBER(12,2)
);

CREATE OR REPLACE TABLE CLEAN.CLAIMS (
  CLAIM_ID STRING, POLICY_NUMBER STRING, LOSS_DATE DATE, LOSS_TYPE STRING,
  NARRATIVE STRING, CLAIMED_AMOUNT NUMBER(12,2), REPORTED_AT TIMESTAMP_NTZ
);

-- CURATED: PDS knowledge base. Snowflake's VECTOR type is dense only, so sparse vectors
-- are stored as parallel INDICES / VALUES arrays (fastembed SPLADE/BM25 output).
CREATE OR REPLACE TABLE CURATED.PDS_CHUNKS (
  CHUNK_ID STRING, DOC_ID STRING, DOC_VERSION STRING,
  SECTION STRING, CLAUSE_ID STRING, PAGE NUMBER,
  CHUNK_TEXT STRING, CHUNK_INDEX NUMBER, LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE CURATED.PDS_SPARSE_VECTORS (
  CHUNK_ID STRING, MODEL STRING,
  INDICES ARRAY, VALS ARRAY,
  LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- CURATED: agent output. A person decides every claim; the agent only recommends.
CREATE OR REPLACE TABLE CURATED.CLAIM_ASSESSMENTS (
  ASSESSMENT_ID STRING DEFAULT UUID_STRING(), CLAIM_ID STRING,
  RECOMMENDATION STRING,            -- ACCEPT | DECLINE | REFER
  SUMMARY STRING, RATIONALE STRING,
  CLAUSE_IDS ARRAY, CONFIDENCE NUMBER(4,3),
  MODEL STRING, PROMPT_VERSION STRING,
  CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE CURATED.CLAIM_DECISIONS (
  DECISION_ID STRING DEFAULT UUID_STRING(), CLAIM_ID STRING, ASSESSMENT_ID STRING,
  DECISION STRING,                  -- ACCEPT | DECLINE
  OVERRIDE_OF_AGENT BOOLEAN, REASON STRING, CLAUSE_IDS ARRAY,
  DECIDED_BY STRING, DECIDED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE CURATED.DECISION_VERIFICATIONS (
  VERIFICATION_ID STRING DEFAULT UUID_STRING(), DECISION_ID STRING, CLAIM_ID STRING,
  SUPPORTED BOOLEAN,                -- is the decision backed by a PDS clause?
  FINDING STRING, CLAUSE_IDS ARRAY, SEVERITY STRING,   -- OK | REVIEW | UNSUPPORTED_DECLINE
  MODEL STRING, VERIFIED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE CURATED.CLAIMS_REPORT (
  REPORT_ID STRING DEFAULT UUID_STRING(), PERIOD_START DATE, PERIOD_END DATE,
  CLAIMS_TOTAL NUMBER, DECLINED NUMBER, UNSUPPORTED_DECLINES NUMBER, OVERRIDES NUMBER,
  NARRATIVE STRING, CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE TABLE CURATED.DAG_RUN_LOG (
  RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(), CLAIMS_TOTAL NUMBER, UNASSESSED NUMBER
);

-- 500 synthetic motor policies
INSERT INTO RAW.POLICIES_RAW (POLICY_NUMBER, HOLDER_NAME, PRODUCT, START_DATE, SUM_INSURED)
SELECT 'POL' || LPAD((ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1)::STRING, 6, '0'),
       'Holder ' || ROW_NUMBER() OVER (ORDER BY SEQ4()),
       'Motor',
       DATEADD(day, -UNIFORM(10, 1500, RANDOM()), CURRENT_DATE()),
       UNIFORM(5000, 150000, RANDOM())
FROM TABLE(GENERATOR(ROWCOUNT => 500));

-- 300 synthetic motor claims with narratives. Some narratives touch common PDS exclusion themes
-- (unlicensed driver, racing, wear and tear, intentional damage) so the Advisor has real decisions to make.
INSERT INTO RAW.CLAIMS_RAW (CLAIM_ID, POLICY_NUMBER, LOSS_DATE, LOSS_TYPE, NARRATIVE, CLAIMED_AMOUNT, REPORTED_AT)
WITH base AS (
  SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS N, UNIFORM(0, 9, RANDOM()) AS K
  FROM TABLE(GENERATOR(ROWCOUNT => 300))
)
SELECT 'CLM' || LPAD(N::STRING, 7, '0'),
       'POL' || LPAD(UNIFORM(0, 499, RANDOM())::STRING, 6, '0'),
       DATEADD(day, -UNIFORM(1, 120, RANDOM()), CURRENT_DATE()),
       CASE K WHEN 0 THEN 'Collision' WHEN 1 THEN 'Collision' WHEN 2 THEN 'Theft' WHEN 3 THEN 'Hail'
              WHEN 4 THEN 'Windscreen' WHEN 5 THEN 'Fire' WHEN 6 THEN 'Collision' WHEN 7 THEN 'Malicious damage'
              WHEN 8 THEN 'Mechanical' ELSE 'Flood' END,
       CASE K
         WHEN 0 THEN 'Insured driver rear-ended a stationary vehicle at traffic lights. Front bumper and bonnet damaged. No injuries.'
         WHEN 1 THEN 'Vehicle was driven by the policyholder''s adult son, who holds a current licence, and struck a fence while reversing out of the driveway.'
         WHEN 2 THEN 'Vehicle stolen from the street overnight. Keys were inside the house. Police report lodged the next morning.'
         WHEN 3 THEN 'Hailstorm caused dents across the roof and bonnet while the vehicle was parked outdoors.'
         WHEN 4 THEN 'Stone chip cracked the windscreen on the highway. Driver requests replacement.'
         WHEN 5 THEN 'Engine bay fire while parked. Fire brigade attended. Cause is under investigation.'
         WHEN 6 THEN 'Collision at an intersection. The other driver ran a red light. Dashcam footage is available.'
         WHEN 7 THEN 'Panel keyed and mirror smashed while parked at a shopping centre.'
         WHEN 8 THEN 'Gearbox failed on a trip. The vehicle has 240,000 km and was last serviced three years ago.'
         ELSE 'Vehicle damaged by floodwater after driver entered a flooded road during a storm warning.'
       END,
       UNIFORM(300, 60000, RANDOM()),
       DATEADD(hour, -UNIFORM(1, 2000, RANDOM()), CURRENT_TIMESTAMP())
FROM base;

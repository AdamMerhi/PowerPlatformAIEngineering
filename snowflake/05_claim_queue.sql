-- Demo queue: a deterministic ~100-claim sample of V_CLAIM_ASSESSMENT with a
-- useful mix of outcomes (25 ACCEPT, 25 REFER, 50 DECLINE) instead of the
-- real 97% decline skew. DECLINE and REFER rows are spread round-robin across
-- the different cited-clause combinations so every clause shows up.
-- Deterministic: ordering uses HASH(src_row_id), never RANDOM(), so reruns
-- return the same claims. Run as POC_ROLE after 04_claim_assessment.sql.
USE ROLE POC_ROLE;
USE WAREHOUSE CLAIMS_WH;
USE DATABASE CLAIMS_POC;

CREATE OR REPLACE VIEW CURATED.V_CLAIM_QUEUE AS
WITH ranked AS (
  SELECT a.*,
         ROW_NUMBER() OVER (PARTITION BY recommended_outcome, cited_clauses
                            ORDER BY HASH(src_row_id)) AS rn_in_group
  FROM CURATED.V_CLAIM_ASSESSMENT a
),
spread AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY recommended_outcome
                            ORDER BY rn_in_group, HASH(src_row_id)) AS rn_in_outcome
  FROM ranked
)
SELECT src_row_id, veh_body, gender, agecat, driver_age_band, veh_value, exposure, numclaims,
       claim_amount, policy_start_date, policy_end_date, loss_date,
       recommended_outcome, cited_clauses, conditions
FROM spread
WHERE (recommended_outcome = 'ACCEPT'  AND rn_in_outcome <= 25)
   OR (recommended_outcome = 'REFER'   AND rn_in_outcome <= 25)
   OR (recommended_outcome = 'DECLINE' AND rn_in_outcome <= 50);

GRANT SELECT ON VIEW CURATED.V_CLAIM_QUEUE TO ROLE POC_ROLE;

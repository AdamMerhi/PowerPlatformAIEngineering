-- Deterministic assessment of each motor claim against docs/pds/ute-cover-pds.md.
-- Run as POC_ROLE, after DAG C has loaded CURATED.FCT_MOTOR_CLAIMS (dbt build).
-- The view is the ground truth the Verifier re-checks decisions against. The
-- Advisor retrieves the clause TEXT from the PDS (RAG) and uses this view for
-- the outcome, so the LLM explains and cites rather than computing.
-- To change the product rules, edit the single row in the rules CTE below.
USE ROLE POC_ROLE;
USE WAREHOUSE CLAIMS_WH;
USE DATABASE CLAIMS_POC;

CREATE OR REPLACE VIEW CURATED.V_CLAIM_ASSESSMENT AS
WITH rules AS (
  SELECT ARRAY_CONSTRUCT('UTE', 'PANVN', 'TRUCK') AS covered_vehicles,  -- clause 2.1
         'F'    AS eligible_gender,                                      -- clause 2.2
         0.70   AS min_exposure,                                         -- clause 3.2
         200    AS excess,                                               -- clause 4.1
         10000  AS senior_limit,                                         -- clause 4.2
         0.75   AS total_loss_ratio,                                     -- clause 4.3
         3      AS repeat_claims                                         -- clause 6.1
),
checked AS (
  SELECT
    c.src_row_id, c.veh_body, c.gender, c.agecat, c.driver_age_band,
    c.veh_value, c.exposure, c.numclaims, c.claim_amount,
    c.policy_start_date, c.policy_end_date, c.loss_date,
    NOT ARRAY_CONTAINS(c.veh_body::VARIANT, r.covered_vehicles)                   AS d_2_1,
    c.gender <> r.eligible_gender                                                 AS d_2_2,
    c.loss_date < c.policy_start_date OR c.loss_date > c.policy_end_date          AS d_3_1,
    c.claim_amount <= r.excess                                                    AS d_4_1,
    c.exposure < r.min_exposure                                                   AS r_3_2,
    c.claim_amount > r.senior_limit                                               AS r_4_2,
    c.veh_value > 0 AND c.claim_amount >= r.total_loss_ratio * c.veh_value * 10000 AS r_4_3,
    c.veh_value = 0                                                               AS r_4_4,
    c.numclaims >= r.repeat_claims                                                AS r_6_1,
    c.agecat = 1                                                                  AS c_5_1
  FROM CURATED.FCT_MOTOR_CLAIMS c CROSS JOIN rules r
  WHERE c.has_claim
),
clauses AS (
  SELECT *,
    ARRAY_COMPACT(ARRAY_CONSTRUCT(IFF(d_2_1,'2.1',NULL), IFF(d_2_2,'2.2',NULL),
                                  IFF(d_3_1,'3.1',NULL), IFF(d_4_1,'4.1',NULL))) AS decline_clauses,
    ARRAY_COMPACT(ARRAY_CONSTRUCT(IFF(r_3_2,'3.2',NULL), IFF(r_4_2,'4.2',NULL), IFF(r_4_3,'4.3',NULL),
                                  IFF(r_4_4,'4.4',NULL), IFF(r_6_1,'6.1',NULL))) AS refer_clauses
  FROM checked
)
SELECT
  src_row_id, veh_body, gender, agecat, driver_age_band, veh_value, exposure, numclaims,
  claim_amount, policy_start_date, policy_end_date, loss_date,
  CASE WHEN ARRAY_SIZE(decline_clauses) > 0 THEN 'DECLINE'
       WHEN ARRAY_SIZE(refer_clauses) > 0   THEN 'REFER'
       ELSE 'ACCEPT' END AS recommended_outcome,
  CASE WHEN ARRAY_SIZE(decline_clauses) > 0 THEN ARRAY_TO_STRING(decline_clauses, ', ')
       WHEN ARRAY_SIZE(refer_clauses) > 0   THEN ARRAY_TO_STRING(refer_clauses, ', ')
       ELSE NULL END AS cited_clauses,
  IFF(c_5_1, '5.1', NULL) AS conditions
FROM clauses;

GRANT SELECT ON VIEW CURATED.V_CLAIM_ASSESSMENT TO ROLE POC_ROLE;

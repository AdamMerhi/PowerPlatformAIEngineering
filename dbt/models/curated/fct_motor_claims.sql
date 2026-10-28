-- One row per src_row_id. Adds the business metrics the claims-log
-- reporting layer would actually query (severity band, exposure
-- expressed in days, policy year, a convenience claim flag).
with staged as (
    select * from {{ ref('stg_motor_claims') }}
)

select
    src_row_id,
    veh_value,
    exposure,
    round(exposure * 365)              as exposure_days,
    has_claim,
    numclaims,
    claim_amount,
    case
        when not has_claim then 'no_claim'
        when claim_amount < 2000 then 'minor'
        when claim_amount < 10000 then 'moderate'
        else 'severe'
    end                                 as claim_severity_band,
    veh_body,
    veh_age,
    veh_age_band,
    gender,
    area,
    agecat,
    driver_age_band,
    policy_start_date,
    date_part('year', policy_start_date) as policy_year,
    policy_end_date,
    loss_date,
    source_system,
    ingested_at
from staged

-- Typed, business-readable view over RAW.MOTOR_CLAIMS_RAW.
-- Decodes the coded categorical columns dataCar ships with.
with source as (
    select * from {{ source('raw', 'motor_claims_raw') }}
)

select
    src_row_id,
    veh_value,
    exposure,
    clm = 1                         as has_claim,
    numclaims,
    claimcst0                       as claim_amount,
    veh_body,
    veh_age,
    case veh_age
        when 1 then 'newest'
        when 2 then '1-3 years'
        when 3 then '4-6 years'
        when 4 then 'oldest'
    end                              as veh_age_band,
    gender,
    area,
    agecat,
    case agecat
        when 1 then 'youngest'
        when 6 then 'oldest'
        else 'mid'
    end                              as driver_age_band,
    policy_start_date,
    policy_end_date,
    loss_date,
    source_system,
    ingested_at
from source

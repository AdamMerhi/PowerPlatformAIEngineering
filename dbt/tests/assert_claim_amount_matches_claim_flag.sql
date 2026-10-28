-- Cross-field consistency: has_claim should agree with claim_amount,
-- numclaims, and loss_date in both directions. This is the test that
-- would catch, e.g., a row where clm=1 but claimcst0=0, or a "no
-- claim" row that somehow got a loss_date.
select
    src_row_id,
    has_claim,
    claim_amount,
    numclaims,
    loss_date
from {{ ref('fct_motor_claims') }}
where
    (has_claim and (claim_amount <= 0 or numclaims <= 0 or loss_date is null))
    or
    (not has_claim and (claim_amount > 0 or numclaims > 0 or loss_date is not null))

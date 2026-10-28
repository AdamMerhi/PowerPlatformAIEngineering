-- Every non-null loss_date must fall within its own policy's term.
-- Catches a broken date derivation (e.g. a hash change that lets
-- loss_date drift outside [policy_start_date, policy_end_date]).
select src_row_id, policy_start_date, policy_end_date, loss_date
from {{ ref('fct_motor_claims') }}
where loss_date is not null
  and (loss_date < policy_start_date or loss_date > policy_end_date)

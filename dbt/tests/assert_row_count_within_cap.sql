-- Fails (returns rows) if the safety cap was ever exceeded.
-- dataCar has 67,856 rows, so this should never bind in practice --
-- it exists to catch a future, larger source silently blowing past
-- the 100,000-row guard in claims_pipeline/config.py (ROW_CAP).
select count(*) as row_count
from {{ ref('fct_motor_claims') }}
having count(*) > 100000

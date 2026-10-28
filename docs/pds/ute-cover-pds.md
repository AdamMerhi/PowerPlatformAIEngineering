# Outback Ute Cover — Product Disclosure Statement

> **Synthetic document.** Fictional insurer and fictional product, written for the Claims PDS Agent POC.
> Not real insurance terms. Clause numbers are stable IDs: the Advisor and Verifier cite them.

Each clause below is self-contained so it can be embedded and retrieved on its own.
The field in brackets after a clause title is the claims-data column the clause is checked against.

## 1. About this cover

**1.1 What this product is.** Outback Ute Cover is comprehensive motor insurance for work and utility vehicles. It pays for loss or damage to the insured vehicle caused by an accident, theft, fire or storm during the policy period.

**1.2 Who we insure.** We insure a small, defined group of drivers and vehicles. Clauses 2.1 and 2.2 set out exactly who and what is eligible. A claim that falls outside them is not covered, whatever its cause.

## 2. Eligibility

**2.1 Covered vehicles** (`VEH_BODY`). We only cover the following vehicle body types: utility vehicles (UTE), panel vans (PANVN) and trucks (TRUCK). We do not cover sedans, hatchbacks, station wagons, hardtops, coupes, convertibles, roadsters, minibuses, buses or motorised caravans. A claim for a vehicle of any other body type is declined.

**2.2 Eligible drivers** (`GENDER`). This product is offered only to female drivers. A claim where the policy driver is not female is declined. This is a deliberate rule of this synthetic product, used to test whether the agent applies an eligibility clause consistently and whether the Verifier flags it.

## 3. Policy period

**3.1 Loss must occur during the policy period** (`LOSS_DATE`, `POLICY_START_DATE`, `POLICY_END_DATE`). We only pay for loss that happens on or after the policy start date and on or before the policy end date. A claim for a loss outside that period is declined.

**3.2 Short-term policies** (`EXPOSURE`). Exposure is the fraction of the year the policy was in force. Where exposure is below 0.70, the claim is referred to an assessor for manual review before any decision is made.

## 4. Claim amounts

**4.1 Excess** (`CLAIM_AMOUNT`). A standard excess of $200 applies to every claim. A claim of $200 or less is not payable and is declined. For a larger claim we pay the amount above the excess.

**4.2 Senior assessor limit** (`CLAIM_AMOUNT`). A claim above $10,000 is referred to a senior assessor. A claims officer cannot approve it alone.

**4.3 Total loss** (`CLAIM_AMOUNT`, `VEH_VALUE`). Vehicle value is recorded in units of $10,000. Where the claim is 75% or more of the vehicle's value, the vehicle may be a total loss and the claim is referred for a total-loss assessment. We never pay more than the vehicle's market value.

**4.4 Vehicle value not recorded** (`VEH_VALUE`). Where no vehicle value is on file (recorded as 0), we cannot check the claim against the value of the vehicle. The claim is referred so the value can be confirmed.

## 5. Conditions

**5.1 Young driver excess** (`AGECAT`, `DRIVER_AGE_BAND`). Where the driver is in the youngest age band (age category 1), an additional excess of $500 applies. This does not change whether a claim is accepted. It reduces the amount paid.

## 6. Repeat claims

**6.1 Multiple claims in one policy period** (`NUMCLAIMS`). Where three or more claims have been made in the same policy period, the claim is referred for review of the claims history before a decision is made.

## 7. How we decide

**7.1 Order of assessment.** We check the clauses in this order. A claim that fails clause 2.1, 2.2, 3.1 or 4.1 is declined. A claim that passes those but triggers clause 3.2, 4.2, 4.3, 4.4 or 6.1 is referred to an assessor. Any other claim is accepted, subject to the conditions in clause 5.

**7.2 A person decides.** The outcome above is a recommendation. A claims officer reviews it and makes the final decision. Every decision records the clause numbers relied on.

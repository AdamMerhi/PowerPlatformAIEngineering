"""Request, response and LLM-output models for the agent API."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Outcome(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    UNKNOWN = "UNKNOWN"  # referred for review, or a fact needed for the decision is missing


class ClauseRef(BaseModel):
    clause_id: str
    title: str


class ClaimFacts(BaseModel):
    """The facts the agent may reason over. Readable values, as the specialist sees them."""

    claim_id: str
    vehicle_body: str
    gender: str
    driver_age_band: str
    age_category: int
    vehicle_value_dollars: float  # 0 means no value on file
    exposure: float
    number_of_claims: int
    claim_amount: float
    claim_pct_of_vehicle_value: float | None  # None when no vehicle value is on file
    loss_date: str
    policy_start: str
    policy_end: str

    def as_text(self) -> str:
        pct = "not available (no vehicle value on file)" if self.claim_pct_of_vehicle_value is None else (
            f"{self.claim_pct_of_vehicle_value:.1f}%"
        )
        value = "none on file (0)" if not self.vehicle_value_dollars else f"${self.vehicle_value_dollars:,.0f}"
        return "\n".join([
            f"Vehicle body type: {self.vehicle_body}",
            f"Policy driver gender: {self.gender}",
            f"Driver age band: {self.driver_age_band} (age category {self.age_category}; category 1 is the youngest)",
            f"Vehicle value: {value}",
            f"Claim amount: ${self.claim_amount:,.2f}",
            f"Claim as a share of vehicle value: {pct}",
            f"Policy exposure (fraction of the year in force): {self.exposure:.4f}",
            f"Claims in this policy period: {self.number_of_claims}",
            f"Loss date: {self.loss_date}",
            f"Policy period: {self.policy_start} to {self.policy_end}",
        ])


# What the LLM must return (no length constraints: strict structured output does not support them).
class AssessmentDraft(BaseModel):
    outcome: Outcome
    headline: str
    summary: str
    clause_ids: list[str]


class VerifierDraft(BaseModel):
    correct_outcome: Outcome
    reason_supported: bool
    finding: str
    clause_ids: list[str]


class AskDraft(BaseModel):
    answered: bool  # false when the passages do not contain the answer
    answer: str
    clause_ids: list[str]


class Evidence(BaseModel):
    """A passage retrieved from the index and shown to the model: what it read."""

    clause_id: str
    doc_type: str  # "pds" (binding policy term) or "primer" (background only)
    title: str
    text: str
    distance: float | None  # smaller is a closer match; None when included without a search


# What the API returns.
class Assessment(BaseModel):
    claim_id: str
    outcome: Outcome
    headline: str
    summary: str
    clauses: list[ClauseRef]
    pds_version: str
    model: str
    evidence: list[Evidence] | None = None  # only when include_evidence is set


class DecisionCheck(BaseModel):
    claim_id: str
    decision: str  # "Accepted" or "Declined", as submitted by the specialist
    agrees: bool
    reason_supported: bool
    requires_manager: bool
    correct_outcome: Outcome
    finding: str
    clauses: list[ClauseRef]
    pds_version: str
    model: str
    evidence: list[Evidence] | None = None


class AskResponse(BaseModel):
    question: str
    answered: bool
    answer: str
    clauses: list[ClauseRef]
    evidence: list[Evidence]
    pds_version: str
    model: str


class AssessRequest(BaseModel):
    claim_id: str
    refresh: bool = False  # true forces a new assessment instead of the cached one
    include_evidence: bool = False  # true also returns the passages the model read


class VerifyRequest(BaseModel):
    claim_id: str
    decision: str  # "Accepted" or "Declined"
    reason: str = ""
    include_evidence: bool = False


class AskRequest(BaseModel):
    question: str
    claim_id: str | None = None  # optional: ground the answer in one claim's facts

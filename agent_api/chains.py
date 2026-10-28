"""Advisor and Verifier chains.

Both use the same retriever and the same language-model wrapper. The Verifier never sees the Advisor's
answer: it works out the correct outcome itself and then compares it with the specialist's decision, so the
two checks are independent. Conflict decisions are made here in code, not by the model.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Protocol

from pydantic import BaseModel

from agent_api.retrieval import Passage, PassageSource
from agent_api.schemas import (
    Assessment,
    AssessmentDraft,
    ClaimFacts,
    ClauseRef,
    DecisionCheck,
    Outcome,
    VerifierDraft,
)

logger = logging.getLogger(__name__)

ADVISOR_SYSTEM = """You are a motor claims assessor for an insurer. Decide what the Product Disclosure Statement (PDS) \
requires for ONE claim.

Rules:
- Use ONLY the PDS clauses under "PDS CLAUSES". Cite the clause numbers you rely on exactly as written (for example 2.1).
- Apply the order in clause 7.1: the claim is DECLINED if clause 2.1, 2.2, 3.1 or 4.1 is failed; otherwise it is UNKNOWN \
(referred for review) if clause 3.2, 4.2, 4.3, 4.4 or 6.1 applies; otherwise it is APPROVED.
- Never invent a clause, exclusion or threshold. If a fact needed for a clause is missing, the outcome is UNKNOWN.
- "BACKGROUND" passages explain general principles. Never cite them and never treat them as policy terms.
- Check every comparison carefully (dates, thresholds, shares). The vehicle value is already in dollars.

Return: outcome; headline (one plain sentence of at most 15 words giving the verdict and the main reason); summary \
(2 or 3 sentences describing the claim and the decision for the claims specialist); clause_ids (the PDS clause numbers \
that decide the outcome; for APPROVED list the eligibility clauses that were checked and passed, plus 5.1 if it applies)."""

VERIFIER_SYSTEM = """You are an independent reviewer checking a decision that a claims specialist has already made, \
against the Product Disclosure Statement (PDS).

1. First work out for yourself what the PDS requires for this claim (APPROVED, DECLINED, or UNKNOWN when it must be \
referred), using ONLY the PDS CLAUSES. Do not assume the specialist is right. Apply the order in clause 7.1.
2. Then judge the specialist's stated reason. reason_supported is true only if the reason relies on a PDS clause that \
exists in the clauses provided and applies to these facts. It is false if the reason relies on an exclusion, rule or \
amount that is not in the PDS clauses, relies on a clause that does not apply, or is empty for a decline. For an \
accepted claim, reason_supported is true.
3. "BACKGROUND" passages explain general principles. Never cite them and never treat them as policy terms.

Return: correct_outcome; reason_supported; finding (one or two sentences naming the clauses and explaining any \
disagreement); clause_ids (the PDS clause numbers that decide the outcome)."""


class AgentError(RuntimeError):
    """The language model could not produce a valid answer."""


class StructuredLLM(Protocol):
    model: str

    def run(self, schema: type[BaseModel], system: str, user: str) -> BaseModel: ...


class OpenAIStructuredLLM:
    """LangChain chat model against the Azure OpenAI v1 endpoint, returning a validated Pydantic object."""

    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI

        self.model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "powerapps-pds")
        # No temperature is set: the deployment is a reasoning model, which only accepts its default.
        self._chat = ChatOpenAI(
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            model=self.model,
            max_retries=2,
            timeout=90,
        )

    def run(self, schema: type[BaseModel], system: str, user: str) -> BaseModel:
        return self._chat.with_structured_output(schema).invoke([("system", system), ("human", user)])


RETRY_BACKOFF = float(os.environ.get("AGENT_RETRY_BACKOFF", "5"))  # seconds, multiplied by the attempt number


def _call(llm: StructuredLLM, schema: type[BaseModel], system: str, user: str, attempts: int = 3) -> BaseModel:
    """Call the model, backing off and retrying on rate limits (HTTP 429) and transient failures."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return llm.run(schema, system, user)
        except Exception as exc:  # noqa: BLE001 - any model/network/schema failure becomes a clean AgentError
            last = exc
            logger.warning("LLM call failed (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF * attempt)
    raise AgentError(f"language model call failed: {last}")


def _clean_ids(raw: list[str]) -> list[str]:
    cleaned = (re.sub(r"(?i)^clause\s+", "", c.strip()).rstrip(".") for c in raw)
    return list(dict.fromkeys(c for c in cleaned if c))


def _render(passages: list[Passage], doc_type: str) -> str:
    return "\n".join(f"- {p.text}" for p in passages if p.doc_type == doc_type) or "(none)"


def _refs(source: PassageSource, ids: list[str]) -> list[ClauseRef]:
    return [ClauseRef(clause_id=i, title=source.title_of(i)) for i in ids]


class Advisor:
    def __init__(self, llm: StructuredLLM, source: PassageSource) -> None:
        self.llm, self.source = llm, source

    def assess(self, facts: ClaimFacts) -> Assessment:
        passages = self.source.for_claim(facts)
        user = (f"CLAIM FACTS:\n{facts.as_text()}\n\nPDS CLAUSES:\n{_render(passages, 'pds')}"
                f"\n\nBACKGROUND:\n{_render(passages, 'primer')}")
        try:
            draft = _call(self.llm, AssessmentDraft, ADVISOR_SYSTEM, user)
        except AgentError:
            return Assessment(
                claim_id=facts.claim_id, outcome=Outcome.UNKNOWN,
                headline="Automatic assessment unavailable, review manually.",
                summary="The assessment service could not produce a result for this claim.",
                clauses=[], pds_version=self.source.pds_version, model=self.llm.model,
            )
        valid = [c for c in _clean_ids(draft.clause_ids) if c in self.source.pds_clause_ids()]
        outcome, headline = draft.outcome, draft.headline.strip()[:140]
        if outcome == Outcome.DECLINED and not valid:
            # A decline must rest on a real PDS clause (the ASIC lesson); otherwise fall back to a referral.
            outcome, headline = Outcome.UNKNOWN, "Could not tie a decline to a PDS clause, review manually."
        return Assessment(
            claim_id=facts.claim_id, outcome=outcome, headline=headline, summary=draft.summary.strip(),
            clauses=_refs(self.source, valid), pds_version=self.source.pds_version, model=self.llm.model,
        )


class Verifier:
    def __init__(self, llm: StructuredLLM, source: PassageSource) -> None:
        self.llm, self.source = llm, source

    def verify(self, facts: ClaimFacts, decision: str, reason: str) -> DecisionCheck:
        label = decision.strip().lower()
        if label not in ("accepted", "declined"):
            raise ValueError("decision must be 'Accepted' or 'Declined'")
        decided = Outcome.APPROVED if label == "accepted" else Outcome.DECLINED
        passages = self.source.for_claim(facts, reason)
        user = (f"CLAIM FACTS:\n{facts.as_text()}\n\nSPECIALIST DECISION: {decision.strip()}"
                f"\nSPECIALIST REASON: {reason.strip() or '(none given)'}"
                f"\n\nPDS CLAUSES:\n{_render(passages, 'pds')}\n\nBACKGROUND:\n{_render(passages, 'primer')}")
        draft = _call(self.llm, VerifierDraft, VERIFIER_SYSTEM, user)  # raises AgentError if it cannot verify
        valid = [c for c in _clean_ids(draft.clause_ids) if c in self.source.pds_clause_ids()]
        agrees = draft.correct_outcome == decided
        supported = draft.reason_supported if decided == Outcome.DECLINED else True
        return DecisionCheck(
            claim_id=facts.claim_id, decision=decision.strip().capitalize(), agrees=agrees,
            reason_supported=supported, requires_manager=(not agrees) or (not supported),
            correct_outcome=draft.correct_outcome, finding=draft.finding.strip(),
            clauses=_refs(self.source, valid), pds_version=self.source.pds_version, model=self.llm.model,
        )

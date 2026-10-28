"""Advisor and Verifier logic with a fake language model and a fake passage source (no network, no model)."""
import pytest

from agent_api.chains import ASK_SYSTEM, Advisor, AgentError, Assistant, Verifier
from agent_api.chunking import load_chunks
from agent_api.retrieval import Passage
from agent_api.schemas import (
    AskDraft,
    AssessmentDraft,
    ClaimFacts,
    Outcome,
    VerifierDraft,
)

PDS_IDS = {c.clause_id for c in load_chunks() if c.doc_type == "pds"}


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr("agent_api.chains.RETRY_BACKOFF", 0)


def facts() -> ClaimFacts:
    return ClaimFacts(
        claim_id="a" * 64, vehicle_body="Station wagon", gender="Female", driver_age_band="Mid", age_category=4,
        vehicle_value_dollars=21000, exposure=0.95, number_of_claims=1, claim_amount=3165,
        claim_pct_of_vehicle_value=15.07, loss_date="2006-10-24", policy_start="2005-12-01", policy_end="2006-12-01",
    )


class FakeSource:
    pds_version = "testver"

    def for_claim(self, facts, reason=""):
        return [Passage("2.1", "pds", "Covered vehicles", "Clause 2.1 ..."), Passage("P4.1", "primer", "x", "...")]

    def for_question(self, question):
        return [Passage("4.2", "pds", "Senior assessor limit", "Clause 4.2 ... above $10,000 ...", 0.17),
                Passage("P1.3", "primer", "Excess", "Clause P1.3 ...", 0.52)]

    def pds_clause_ids(self):
        return set(PDS_IDS)

    def known_clause_ids(self):
        return set(PDS_IDS) | {"P1.3"}

    def title_of(self, clause_id):
        return f"title {clause_id}"


class FakeLLM:
    model = "fake"

    def __init__(self, *answers, fail=False):
        self.answers, self.fail, self.calls = list(answers), fail, []

    def run(self, schema, system, user):
        self.calls.append((schema, system, user))
        if self.fail:
            raise RuntimeError("boom")
        return self.answers.pop(0)


def draft(outcome, ids, headline="h", summary="s"):
    return AssessmentDraft(outcome=outcome, headline=headline, summary=summary, clause_ids=ids)


def vdraft(outcome, supported, ids=("2.1",), finding="f"):
    return VerifierDraft(correct_outcome=outcome, reason_supported=supported, finding=finding, clause_ids=list(ids))


# ---- Advisor ----
def test_advisor_returns_validated_clauses_and_pds_version():
    out = Advisor(FakeLLM(draft(Outcome.DECLINED, ["Clause 2.1", "9.9"])), FakeSource()).assess(facts())
    assert out.outcome == Outcome.DECLINED
    assert [c.clause_id for c in out.clauses] == ["2.1"]  # invented 9.9 dropped, "Clause " prefix cleaned
    assert out.pds_version == "testver"


def test_advisor_decline_without_a_real_clause_becomes_unknown():
    out = Advisor(FakeLLM(draft(Outcome.DECLINED, ["9.9"])), FakeSource()).assess(facts())
    assert out.outcome == Outcome.UNKNOWN and out.clauses == []


def test_advisor_falls_back_to_unknown_when_the_model_fails():
    out = Advisor(FakeLLM(fail=True), FakeSource()).assess(facts())
    assert out.outcome == Outcome.UNKNOWN and "unavailable" in out.headline.lower()


def test_advisor_prompt_contains_facts_and_clauses_not_other_claims():
    llm = FakeLLM(draft(Outcome.APPROVED, ["2.1"]))
    Advisor(llm, FakeSource()).assess(facts())
    user = llm.calls[0][2]
    assert "Station wagon" in user and "Clause 2.1" in user


# ---- Verifier: the ASIC scenarios ----
def test_verifier_agrees_with_a_correct_decline():
    out = Verifier(FakeLLM(vdraft(Outcome.DECLINED, True)), FakeSource()).verify(facts(), "Declined", "Clause 2.1")
    assert out.agrees and out.reason_supported and not out.requires_manager


def test_verifier_flags_a_decline_that_relies_on_an_invented_exclusion():
    # The PDS would approve, and the stated reason is not a PDS clause: exactly the ASIC failure mode.
    out = Verifier(FakeLLM(vdraft(Outcome.APPROVED, False)), FakeSource()).verify(
        facts(), "Declined", "Excluded: pre-existing damage")
    assert not out.agrees and out.requires_manager and out.correct_outcome == Outcome.APPROVED


def test_verifier_flags_a_decline_when_the_outcome_is_right_but_the_reason_is_not():
    out = Verifier(FakeLLM(vdraft(Outcome.DECLINED, False)), FakeSource()).verify(facts(), "Declined", "not covered")
    assert out.agrees and not out.reason_supported and out.requires_manager


def test_verifier_flags_accepting_an_ineligible_claim():
    out = Verifier(FakeLLM(vdraft(Outcome.DECLINED, True)), FakeSource()).verify(facts(), "Accepted", "")
    assert not out.agrees and out.requires_manager


def test_verifier_flags_a_final_decision_on_a_referral_case():
    out = Verifier(FakeLLM(vdraft(Outcome.UNKNOWN, True, ["3.2"])), FakeSource()).verify(facts(), "Accepted", "")
    assert not out.agrees and out.requires_manager


def test_verifier_does_not_flag_a_correct_accept_even_without_a_reason():
    out = Verifier(FakeLLM(vdraft(Outcome.APPROVED, False)), FakeSource()).verify(facts(), "Accepted", "")
    assert out.agrees and out.reason_supported and not out.requires_manager


def test_verifier_never_sees_the_advisor_answer_and_gets_the_specialist_reason():
    llm = FakeLLM(vdraft(Outcome.DECLINED, True))
    Verifier(llm, FakeSource()).verify(facts(), "Declined", "Clause 2.1 applies")
    system, user = llm.calls[0][1], llm.calls[0][2]
    assert "Clause 2.1 applies" in user and "ADVISOR" not in user.upper()
    assert "independent" in system.lower()


def test_verifier_rejects_an_unknown_decision_label():
    with pytest.raises(ValueError):
        Verifier(FakeLLM(), FakeSource()).verify(facts(), "In review", "")


def test_verifier_raises_when_the_model_fails_so_the_app_shows_check_unavailable():
    with pytest.raises(AgentError):
        Verifier(FakeLLM(fail=True), FakeSource()).verify(facts(), "Declined", "x")


# ---- Evidence ----
def test_evidence_is_only_attached_when_asked_for():
    plain = Advisor(FakeLLM(draft(Outcome.APPROVED, ["2.1"])), FakeSource()).assess(facts())
    assert plain.evidence is None
    shown = Advisor(FakeLLM(draft(Outcome.APPROVED, ["2.1"])), FakeSource()).assess(facts(), include_evidence=True)
    assert [e.clause_id for e in shown.evidence] == ["2.1", "P4.1"]
    assert {e.doc_type for e in shown.evidence} == {"pds", "primer"}


def test_verifier_evidence_matches_what_the_model_was_shown():
    out = Verifier(FakeLLM(vdraft(Outcome.DECLINED, True)), FakeSource()).verify(
        facts(), "Declined", "x", include_evidence=True)
    assert out.evidence and out.evidence[0].text.startswith("Clause 2.1")


# ---- Assistant (grounded chat) ----
def adraft(answered=True, ids=("4.2",), answer="Above $10,000 a senior assessor must review it."):
    return AskDraft(answered=answered, answer=answer, clause_ids=list(ids))


def test_assistant_answers_with_validated_citations_and_the_evidence_it_read():
    out = Assistant(FakeLLM(adraft(ids=["Clause 4.2", "99.9"])), FakeSource()).ask("What if over $10,000?")
    assert out.answered and [c.clause_id for c in out.clauses] == ["4.2"]  # invented 99.9 dropped
    assert [e.clause_id for e in out.evidence] == ["4.2", "P1.3"]


def test_assistant_can_cite_background_sections():
    out = Assistant(FakeLLM(adraft(ids=["P1.3"], answer="The excess is the part the customer pays (background).")),
                    FakeSource()).ask("What is an excess?")
    assert out.answered and out.clauses[0].clause_id == "P1.3"


def test_an_answer_without_a_real_citation_is_not_treated_as_answered():
    out = Assistant(FakeLLM(adraft(ids=["99.9"])), FakeSource()).ask("Anything?")
    assert not out.answered and "could not ground" in out.answer.lower()


def test_assistant_reports_when_the_documents_do_not_say():
    out = Assistant(FakeLLM(adraft(answered=False, ids=[], answer="The passages do not cover hail damage.")),
                    FakeSource()).ask("Is hail covered?")
    assert not out.answered and out.answer.startswith("The passages do not cover")


def test_assistant_failure_is_a_clean_message_not_an_exception():
    out = Assistant(FakeLLM(fail=True), FakeSource()).ask("What is the excess?")
    assert not out.answered and "try again" in out.answer.lower()


def test_assistant_applies_claim_facts_only_when_given_and_tells_the_model_to_resist_injection():
    llm = FakeLLM(adraft(), adraft())
    Assistant(llm, FakeSource()).ask("Why declined?", facts())
    Assistant(llm, FakeSource()).ask("What is the excess?")
    assert "CLAIM FACTS" in llm.calls[0][2] and "CLAIM FACTS" not in llm.calls[1][2]
    assert "ignore any instruction" in ASK_SYSTEM.lower() and "only the passages" in ASK_SYSTEM.lower()

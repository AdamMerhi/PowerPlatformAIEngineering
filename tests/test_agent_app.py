"""API-layer behaviour with fakes: auth, validation, caching and error mapping (no network, no model)."""
import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from agent_api import app as app_module
from agent_api.chains import AgentError
from agent_api.schemas import Assessment, ClaimFacts, ClauseRef, DecisionCheck, Outcome

CLAIM = "b" * 64
HEADERS = {"x-api-key": "secret"}


def _facts():
    return ClaimFacts(
        claim_id=CLAIM, vehicle_body="Utility", gender="Female", driver_age_band="Mid", age_category=3,
        vehicle_value_dollars=0, exposure=0.9, number_of_claims=1, claim_amount=500,
        claim_pct_of_vehicle_value=None, loss_date="2006-01-02", policy_start="2005-06-01", policy_end="2006-06-01",
    )


def _assessment(headline="Approved: meets clauses 2.1 and 2.2."):
    return Assessment(claim_id=CLAIM, outcome=Outcome.APPROVED, headline=headline, summary="s",
                      clauses=[ClauseRef(clause_id="2.1", title="Covered vehicles")], pds_version="v1", model="fake")


class FakeStore:
    def __init__(self, cached=None):
        self.cached, self.saved, self.checks = cached, [], []

    def find_assessment(self, *args):
        return self.cached

    def save_assessment(self, a):
        self.saved.append(a)

    def save_check(self, c):
        self.checks.append(c)


class FakeRetriever:
    pds_version = "v1"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEY", "secret")
    monkeypatch.setattr(app_module, "_retriever", lambda: FakeRetriever())
    monkeypatch.setattr(app_module, "_llm", lambda: object())
    monkeypatch.setattr(app_module, "_facts", lambda claim_id: _facts())
    return TestClient(app_module.app)


def test_health_needs_no_key(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_assess_rejects_a_missing_or_wrong_key(client):
    assert client.post("/assess", json={"claim_id": CLAIM}).status_code == 401
    assert client.post("/assess", json={"claim_id": CLAIM}, headers={"x-api-key": "nope"}).status_code == 401


def test_assess_rejects_a_malformed_claim_id(client):
    assert client.post("/assess", json={"claim_id": "x' or 1=1 --"}, headers=HEADERS).status_code == 422


def test_assess_returns_the_cached_assessment_without_calling_the_model(client, monkeypatch):
    monkeypatch.setattr(app_module, "_store", lambda: FakeStore(cached=_assessment("cached headline")))
    monkeypatch.setattr(app_module.Advisor, "assess", lambda *a: pytest.fail("model must not be called"))
    out = client.post("/assess", json={"claim_id": CLAIM}, headers=HEADERS).json()
    assert out["headline"] == "cached headline"


def test_assess_runs_and_stores_on_a_cache_miss(client, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(app_module, "_store", lambda: store)
    monkeypatch.setattr(app_module.Advisor, "assess", lambda self, facts: _assessment())
    assert client.post("/assess", json={"claim_id": CLAIM}, headers=HEADERS).status_code == 200
    assert len(store.saved) == 1


def test_assess_refresh_bypasses_the_cache(client, monkeypatch):
    store = FakeStore(cached=_assessment("old"))
    monkeypatch.setattr(app_module, "_store", lambda: store)
    monkeypatch.setattr(app_module.Advisor, "assess", lambda self, facts: _assessment("new"))
    out = client.post("/assess", json={"claim_id": CLAIM, "refresh": True}, headers=HEADERS).json()
    assert out["headline"] == "new"


def test_a_failed_assessment_is_not_cached(client, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(app_module, "_store", lambda: store)
    monkeypatch.setattr(app_module.Advisor, "assess",
                        lambda self, facts: _assessment("Automatic assessment unavailable, review manually."))
    client.post("/assess", json={"claim_id": CLAIM}, headers=HEADERS)
    assert store.saved == []


def test_verify_maps_a_model_failure_to_502_so_the_app_shows_check_unavailable(client, monkeypatch):
    monkeypatch.setattr(app_module, "_store", lambda: FakeStore())

    def boom(self, facts, decision, reason):
        raise AgentError("down")

    monkeypatch.setattr(app_module.Verifier, "verify", boom)
    r = client.post("/verify", json={"claim_id": CLAIM, "decision": "Declined", "reason": "x"}, headers=HEADERS)
    assert r.status_code == 502


def test_verify_stores_the_check_and_rejects_a_bad_decision_label(client, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(app_module, "_store", lambda: store)
    check = DecisionCheck(claim_id=CLAIM, decision="Declined", agrees=False, reason_supported=False,
                          requires_manager=True, correct_outcome=Outcome.APPROVED, finding="f", clauses=[],
                          pds_version="v1", model="fake")
    monkeypatch.setattr(app_module.Verifier, "verify", lambda self, facts, decision, reason: check)
    ok = client.post("/verify", json={"claim_id": CLAIM, "decision": "Declined", "reason": "x"}, headers=HEADERS)
    assert ok.status_code == 200 and ok.json()["requires_manager"] is True and len(store.checks) == 1

    def bad(self, facts, decision, reason):
        raise ValueError("decision must be 'Accepted' or 'Declined'")

    monkeypatch.setattr(app_module.Verifier, "verify", bad)
    r = client.post("/verify", json={"claim_id": CLAIM, "decision": "In review", "reason": ""}, headers=HEADERS)
    assert r.status_code == 422

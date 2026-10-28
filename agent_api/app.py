"""FastAPI service for the Claims PDS Agent.

    uvicorn agent_api.app:app --host 0.0.0.0 --port 8080

POST /assess  -> Advisor: summary, verdict (APPROVED / DECLINED / UNKNOWN), headline, cited clauses.
                 Cached per (claim, PDS version) in Dataverse; send refresh=true to force a new assessment.
POST /verify  -> Verifier: independent re-check of a submitted Accepted / Declined decision (always stored).
GET  /health  -> liveness (no model or data access, so it is a cheap warm-up call)

Every call except /health needs the `x-api-key` header to match AGENT_API_KEY.
"""
from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException

from agent_api.chains import Advisor, AgentError, OpenAIStructuredLLM, Verifier
from agent_api.claims_source import CLAIM_ID, fetch_facts
from agent_api.retrieval import Retriever
from agent_api.schemas import Assessment, AssessRequest, DecisionCheck, VerifyRequest
from agent_api.store import ResultStore

logger = logging.getLogger("agent_api")
app = FastAPI(title="Claims PDS Agent", version="0.1.0")


def require_key(x_api_key: str = Header(default="")) -> None:
    expected = os.environ.get("AGENT_API_KEY", "")
    if not expected or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@lru_cache(maxsize=1)
def _retriever() -> Retriever:
    return Retriever()


@lru_cache(maxsize=1)
def _llm() -> OpenAIStructuredLLM:
    return OpenAIStructuredLLM()


@lru_cache(maxsize=1)
def _dataverse():
    from claims_pipeline.dataverse import DataverseClient, DataverseConfig

    return DataverseClient(DataverseConfig.from_env())


@lru_cache(maxsize=1)
def _store() -> ResultStore:
    return ResultStore(_dataverse())


def _validated(claim_id: str) -> str:
    if not CLAIM_ID.fullmatch(claim_id):
        raise HTTPException(status_code=422, detail="claim_id must be the 64-character source row id")
    return claim_id


def _facts(claim_id: str):
    try:
        return fetch_facts(_dataverse(), claim_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _best_effort(action: str, fn, *args) -> None:
    """Storing a result must never stop the answer reaching the user."""
    try:
        fn(*args)
    except Exception:
        logger.exception("could not %s", action)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/assess", response_model=Assessment, dependencies=[Depends(require_key)])
def assess(request: AssessRequest) -> Assessment:
    claim_id = _validated(request.claim_id)
    retriever = _retriever()
    if not request.refresh:
        try:
            cached = _store().find_assessment(claim_id, retriever.pds_version, retriever)
        except Exception:
            logger.exception("cache lookup failed")
            cached = None
        if cached:
            return cached
    result = Advisor(_llm(), retriever).assess(_facts(claim_id))
    if "unavailable" not in result.headline.lower():  # never cache a failure
        _best_effort("save assessment", _store().save_assessment, result)
    return result


@app.post("/verify", response_model=DecisionCheck, dependencies=[Depends(require_key)])
def verify(request: VerifyRequest) -> DecisionCheck:
    facts = _facts(_validated(request.claim_id))
    try:
        check = Verifier(_llm(), _retriever()).verify(facts, request.decision, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        logger.error("verification failed: %s", exc)
        raise HTTPException(status_code=502, detail="the check could not be completed") from exc
    _best_effort("save decision check", _store().save_check, check)
    return check

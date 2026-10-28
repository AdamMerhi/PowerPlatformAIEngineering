"""FastAPI service for the Claims PDS Agent.

    uvicorn agent_api.app:app --host 0.0.0.0 --port 8080

POST /assess  -> Advisor: summary, verdict (APPROVED / DECLINED / UNKNOWN), headline, cited clauses.
                 Cached per (claim, PDS version) in Dataverse; refresh=true forces a new assessment.
POST /verify  -> Verifier: independent re-check of a submitted Accepted / Declined decision (always stored).
POST /ask     -> Assistant: grounded question answering over the PDS and the insurance primer, with citations.
GET  /demo    -> single-page demo: assess, check a decision, ask questions, and see the retrieved evidence.
GET  /health  -> liveness (no model or data access, so it is a cheap warm-up call)

Every call except /health and /demo needs the `x-api-key` header to match AGENT_API_KEY.
Each call logs one `event=...` line (no claim facts, no question text) for Log Analytics.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from agent_api.chains import (
    Advisor,
    AgentError,
    Assistant,
    OpenAIStructuredLLM,
    Verifier,
    evidence_of,
)
from agent_api.claims_source import CLAIM_ID, fetch_facts
from agent_api.retrieval import Retriever
from agent_api.schemas import (
    AskRequest,
    AskResponse,
    Assessment,
    AssessRequest,
    DecisionCheck,
    VerifyRequest,
)
from agent_api.store import ResultStore

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("agent_api")
app = FastAPI(title="Claims PDS Agent", version="0.2.0")
DEMO_PAGE = Path(__file__).with_name("demo.html")


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


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo() -> str:
    return DEMO_PAGE.read_text(encoding="utf-8")


@app.post("/assess", response_model=Assessment, dependencies=[Depends(require_key)])
def assess(request: AssessRequest) -> Assessment:
    started = time.perf_counter()
    claim_id = _validated(request.claim_id)
    retriever = _retriever()
    result, cached = None, False
    if not request.refresh:
        try:
            result = _store().find_assessment(claim_id, retriever.pds_version, retriever)
            cached = result is not None
        except Exception:
            logger.exception("cache lookup failed")
    facts = None
    if result is None:
        facts = _facts(claim_id)
        result = Advisor(_llm(), retriever).assess(facts, include_evidence=request.include_evidence)
        if "unavailable" not in result.headline.lower():  # never cache a failure
            _best_effort("save assessment", _store().save_assessment, result)
    elif request.include_evidence:
        result.evidence = evidence_of(retriever.for_claim(_facts(claim_id)))  # retrieval is deterministic
    logger.info("event=assess claim=%s cached=%s outcome=%s clauses=%s ms=%d", claim_id[:8], cached,
                result.outcome.value, ",".join(c.clause_id for c in result.clauses), _ms(started))
    return result


@app.post("/verify", response_model=DecisionCheck, dependencies=[Depends(require_key)])
def verify(request: VerifyRequest) -> DecisionCheck:
    started = time.perf_counter()
    facts = _facts(_validated(request.claim_id))
    try:
        check = Verifier(_llm(), _retriever()).verify(facts, request.decision, request.reason,
                                                      include_evidence=request.include_evidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        logger.error("event=verify_failed claim=%s ms=%d error=%s", request.claim_id[:8], _ms(started), exc)
        raise HTTPException(status_code=502, detail="the check could not be completed") from exc
    _best_effort("save decision check", _store().save_check, check)
    logger.info("event=verify claim=%s decision=%s agrees=%s reason_supported=%s requires_manager=%s ms=%d",
                request.claim_id[:8], check.decision, check.agrees, check.reason_supported,
                check.requires_manager, _ms(started))
    return check


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_key)])
def ask(request: AskRequest) -> AskResponse:
    started = time.perf_counter()
    question = request.question.strip()
    if not 3 <= len(question) <= 500:
        raise HTTPException(status_code=422, detail="question must be 3 to 500 characters")
    facts = _facts(_validated(request.claim_id)) if request.claim_id else None
    response = Assistant(_llm(), _retriever()).ask(question, facts)
    logger.info("event=ask answered=%s with_claim=%s clauses=%s question_chars=%d ms=%d", response.answered,
                facts is not None, ",".join(c.clause_id for c in response.clauses), len(question), _ms(started))
    return response

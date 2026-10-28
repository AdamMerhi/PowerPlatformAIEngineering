"""Persist agent results to Dataverse and serve cached assessments.

An assessment is cached per (claim, PDS version): changing the policy documents changes the version, which
automatically invalidates every cached assessment. Decision checks are an audit trail, never cached.
"""
from __future__ import annotations

import logging

from agent_api.retrieval import PassageSource
from agent_api.schemas import Assessment, ClauseRef, DecisionCheck, Outcome
from claims_pipeline.dataverse import DataverseClient

logger = logging.getLogger(__name__)


def _join(clauses: list[ClauseRef]) -> str:
    return ";".join(c.clause_id for c in clauses)


def _split(raw: str | None, source: PassageSource) -> list[ClauseRef]:
    return [ClauseRef(clause_id=c, title=source.title_of(c)) for c in (raw or "").split(";") if c]


class ResultStore:
    def __init__(self, client: DataverseClient) -> None:
        self.client = client
        self._sets: dict[str, str] = {}

    def _entity_set(self, suffix: str) -> str:
        if suffix not in self._sets:
            logical = f"{self.client.prefix}_{suffix}"
            resp = self.client._request("GET", f"/EntityDefinitions(LogicalName='{logical}')?$select=EntitySetName")
            if resp.status_code == 404:
                raise LookupError(f"table {logical} does not exist; run `python -m claims_pipeline.dataverse create-table`")
            self._sets[suffix] = resp.json()["EntitySetName"]
        return self._sets[suffix]

    def find_assessment(self, claim_id: str, pds_version: str, source: PassageSource) -> Assessment | None:
        """claim_id must already be validated as a 64-character hex id (it is placed in a filter)."""
        p = self.client.prefix
        query = (f"/{self._entity_set('claimassessment')}?$filter={p}_claimkey eq '{claim_id}' "
                 f"and {p}_pdsversion eq '{pds_version}'&$orderby=createdon desc&$top=1")
        records = self.client._request("GET", query).json().get("value", [])
        if not records:
            return None
        r = records[0]
        return Assessment(
            claim_id=claim_id, outcome=Outcome(r[f"{p}_outcome"]), headline=r[f"{p}_headline"] or "",
            summary=r[f"{p}_summary"] or "", clauses=_split(r[f"{p}_clauses"], source),
            pds_version=pds_version, model=r[f"{p}_model"] or "",
        )

    def save_assessment(self, a: Assessment) -> None:
        p = self.client.prefix
        self.client._request("POST", f"/{self._entity_set('claimassessment')}", json={
            f"{p}_headline": a.headline, f"{p}_claimkey": a.claim_id, f"{p}_outcome": a.outcome.value,
            f"{p}_summary": a.summary, f"{p}_clauses": _join(a.clauses), f"{p}_pdsversion": a.pds_version,
            f"{p}_model": a.model,
        })

    def save_check(self, c: DecisionCheck) -> None:
        p = self.client.prefix
        headline = f"{c.decision}: " + ("requires line manager" if c.requires_manager else "agrees with PDS")
        self.client._request("POST", f"/{self._entity_set('decisioncheck')}", json={
            f"{p}_headline": headline, f"{p}_claimkey": c.claim_id, f"{p}_decision": c.decision,
            f"{p}_agrees": c.agrees, f"{p}_reasonsupported": c.reason_supported,
            f"{p}_requiresmanager": c.requires_manager, f"{p}_correctoutcome": c.correct_outcome.value,
            f"{p}_finding": c.finding, f"{p}_clauses": _join(c.clauses), f"{p}_pdsversion": c.pds_version,
            f"{p}_model": c.model,
        })

"""LanceDB retrieval over the embedded policy documents.

The index is built once (at image build time) by `python -m agent_api.index_build` and opened read-only
at runtime, so there is no hosted vector service and no idle cost.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_api.schemas import ClaimFacts

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge convention for queries
TABLE = "chunks"
INDEX_DIR = Path(os.environ.get("AGENT_INDEX_DIR", Path(__file__).resolve().parent / "index"))
MODEL_CACHE = os.environ.get("FASTEMBED_CACHE_PATH") or None
ALWAYS_INCLUDE = ("pds:7.1",)  # the order in which clauses are applied


@dataclass(frozen=True)
class Passage:
    clause_id: str
    doc_type: str  # "pds" (binding) or "primer" (background)
    title: str
    text: str
    distance: float | None = None  # smaller is a closer match; None for passages added without a search


class PassageSource(Protocol):
    pds_version: str

    def for_claim(self, facts: ClaimFacts, reason: str = "") -> list[Passage]: ...

    def for_question(self, question: str) -> list[Passage]: ...

    def pds_clause_ids(self) -> set[str]: ...

    def known_clause_ids(self) -> set[str]: ...

    def title_of(self, clause_id: str) -> str: ...


def embed_texts(texts: list[str], embedder=None) -> list[list[float]]:
    if embedder is None:
        from fastembed import TextEmbedding

        embedder = TextEmbedding(model_name=EMBED_MODEL, cache_dir=MODEL_CACHE)
    return [vector.tolist() for vector in embedder.embed(texts)]


class Retriever:
    def __init__(self, index_dir: Path = INDEX_DIR, embedder=None):
        import lancedb

        meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
        self.pds_version: str = meta["docs_version"]
        self._table = lancedb.connect(str(index_dir)).open_table(TABLE)
        self._embedder = embedder
        rows = self._table.to_arrow().to_pylist()
        self._by_id = {r["chunk_id"]: r for r in rows}
        self._pds_ids = {r["clause_id"] for r in rows if r["doc_type"] == "pds"}

    def pds_clause_ids(self) -> set[str]:
        return set(self._pds_ids)

    def known_clause_ids(self) -> set[str]:
        """Every clause the index holds, policy terms and background alike."""
        return {r["clause_id"] for r in self._by_id.values()}

    def title_of(self, clause_id: str) -> str:
        row = self._by_id.get(f"pds:{clause_id}") or self._by_id.get(f"primer:{clause_id}")
        return row["title"] if row else ""

    def _search(self, query: str, k: int, doc_type: str) -> list[dict]:
        vector = embed_texts([QUERY_PREFIX + query], self._embedder)[0]
        return (
            self._table.search(vector).where(f"doc_type = '{doc_type}'").limit(k).to_list()
        )

    def for_claim(self, facts: ClaimFacts, reason: str = "") -> list[Passage]:
        """One query per kind of check (vehicle, driver, dates, amounts...) plus any reason the specialist gave."""
        queries = [
            f"covered vehicle body types, eligibility of a {facts.vehicle_body}",
            f"eligible drivers, policy driver is {facts.gender}",
            "loss must occur during the policy period start and end date",
            "excess, claim amount at or below the excess is not payable",
            "short-term policy exposure below threshold referred to assessor",
            "claim amount above limit referred to senior assessor",
            "total loss claim is a large share of the vehicle value",
            "vehicle value not recorded referred",
            "repeat claims in the same policy period referred for review",
            "young driver additional excess",
        ]
        if reason.strip():
            queries.append(reason.strip())
        chosen: dict[str, dict] = {}
        for query in queries:
            for row in self._search(query, 2, "pds"):
                self._keep_closest(chosen, row)
        for chunk_id in ALWAYS_INCLUDE:
            if chunk_id in self._by_id:
                chosen.setdefault(chunk_id, self._by_id[chunk_id])
        for row in self._search("a decline must rest on a policy term; referral is not a decision", 2, "primer"):
            self._keep_closest(chosen, row)
        return self._passages(chosen)

    def for_question(self, question: str) -> list[Passage]:
        """Free-form question: only the few closest policy clauses and background sections, not the whole PDS."""
        chosen: dict[str, dict] = {}
        for row in self._search(question, 4, "pds") + self._search(question, 2, "primer"):
            self._keep_closest(chosen, row)
        return self._passages(chosen, by_distance=True)

    @staticmethod
    def _keep_closest(chosen: dict[str, dict], row: dict) -> None:
        known = chosen.get(row["chunk_id"])
        if known is None or row.get("_distance", 9) < known.get("_distance", 9):
            chosen[row["chunk_id"]] = row

    @staticmethod
    def _passages(chosen: dict[str, dict], by_distance: bool = False) -> list[Passage]:
        passages = [
            Passage(r["clause_id"], r["doc_type"], r["title"], r["text"],
                    round(float(r["_distance"]), 3) if r.get("_distance") is not None else None)
            for r in chosen.values()
        ]
        if by_distance:  # closest first (chat); claims keep clause-number order so their prompts are unchanged
            return sorted(passages, key=lambda p: (p.doc_type != "pds", p.distance if p.distance is not None else 9))
        return sorted(passages, key=lambda p: (p.doc_type != "pds", p.clause_id))

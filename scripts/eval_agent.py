"""Evaluate the Advisor and Verifier against the SQL rules view (the oracle).

    python scripts/eval_agent.py --per-class 10 --workers 4

Reads .env for Snowflake and Azure OpenAI settings. Costs a few cents per run. Exits non-zero if a target is missed.
Targets: Advisor outcome agrees with the oracle on >= 95%; every cited clause exists in the PDS (100%);
Verifier flags every wrong decision and none of the correct ones.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip())

from check_snowflake import connect

from agent_api.chains import Advisor, AgentError, OpenAIStructuredLLM, Verifier
from agent_api.claims_source import facts_from_snowflake
from agent_api.retrieval import Retriever
from agent_api.schemas import Outcome

ORACLE = {"ACCEPT": Outcome.APPROVED, "DECLINE": Outcome.DECLINED, "REFER": Outcome.UNKNOWN}
SAMPLE_SQL = """
select * from (
  select *, row_number() over (partition by recommended_outcome, cited_clauses order by hash(src_row_id)) as rn_group
  from CURATED.V_CLAIM_ASSESSMENT
) qualify row_number() over (partition by recommended_outcome order by rn_group, hash(src_row_id)) <= {n}
"""


def sample(per_class: int) -> list[dict]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(SAMPLE_SQL.format(n=per_class))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-class", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    rows = sample(args.per_class)
    llm, source = OpenAIStructuredLLM(), Retriever()
    advisor, verifier = Advisor(llm, source), Verifier(llm, source)
    pds_ids = source.pds_clause_ids()

    def run_advisor(row):
        facts = facts_from_snowflake(row)
        result = advisor.assess(facts)
        oracle_clauses = {c.strip() for c in (row["CITED_CLAUSES"] or "").split(",") if c.strip()}
        return {
            "id": row["SRC_ROW_ID"][:8], "oracle": ORACLE[row["RECOMMENDED_OUTCOME"]], "got": result.outcome,
            "valid_ids": all(c.clause_id in pds_ids for c in result.clauses),
            "clause_overlap": bool(oracle_clauses & {c.clause_id for c in result.clauses}) if oracle_clauses else True,
            # For declines and referrals the cited clauses should be exactly the ones that failed or applied.
            "clause_exact": ({c.clause_id for c in result.clauses} == oracle_clauses) if oracle_clauses else None,
            "headline": result.headline,
        }

    def run_verifier(row):
        facts, oracle = facts_from_snowflake(row), row["RECOMMENDED_OUTCOME"]
        clauses = row["CITED_CLAUSES"] or ""
        cases = []  # (label, decision, reason, expect_conflict)
        if oracle == "ACCEPT":
            cases += [("correct accept", "Accepted", "", False),
                      ("ASIC: decline on invented exclusion", "Declined", "Excluded: pre-existing damage", True)]
        elif oracle == "DECLINE":
            cases += [("correct decline", "Declined", f"Clause {clauses.split(',')[0].strip()} applies", False),
                      ("accept an ineligible claim", "Accepted", "", True),
                      ("ASIC: right outcome, invented reason", "Declined", "Excluded under the wear and tear exclusion", True)]
        else:
            cases += [("final decision on a referral", "Accepted", "", True)]
        out = []
        for label, decision, reason, expect in cases:
            try:
                got = verifier.verify(facts, decision, reason).requires_manager
            except AgentError:
                got = None
            out.append({"id": row["SRC_ROW_ID"][:8], "label": label, "expect": expect, "got": got})
        return out

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        adv = list(pool.map(run_advisor, rows))
        ver = [r for group in pool.map(run_verifier, rows) for r in group]

    total = len(adv)
    agree = sum(a["got"] == a["oracle"] for a in adv)
    valid = sum(a["valid_ids"] for a in adv)
    overlap = sum(a["clause_overlap"] for a in adv)
    print(f"\nADVISOR  ({total} claims)")
    print(f"  outcome agrees with oracle : {agree}/{total} = {agree / total:.0%}")
    print(f"  all cited clauses exist    : {valid}/{total}")
    print(f"  cites an oracle clause     : {overlap}/{total}")
    exact = [a["clause_exact"] for a in adv if a["clause_exact"] is not None]
    print(f"  cites exactly the oracle's : {sum(exact)}/{len(exact)} (declines and referrals only)")
    for a in adv:
        if a["clause_exact"] is False:
            print(f"    differs {a['id']}: {a['headline']}")
    print("  confusion (oracle -> agent):", dict(Counter((a['oracle'].value, a['got'].value) for a in adv)))
    for a in adv:
        if a["got"] != a["oracle"]:
            print(f"  MISS {a['id']}: oracle {a['oracle'].value}, agent {a['got'].value}: {a['headline']}")

    print(f"\nVERIFIER ({len(ver)} checks)")
    bad = [v for v in ver if v["got"] is None or v["got"] != v["expect"]]
    for label in sorted({v["label"] for v in ver}):
        group = [v for v in ver if v["label"] == label]
        ok = sum(v["got"] == v["expect"] for v in group)
        print(f"  {label:<40} {ok}/{len(group)} (expected conflict: {group[0]['expect']})")
    for v in bad:
        print(f"  MISS {v['id']}: {v['label']} expected {v['expect']} got {v['got']}")

    passed = agree / total >= 0.95 and valid == total and not bad
    print("\nRESULT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

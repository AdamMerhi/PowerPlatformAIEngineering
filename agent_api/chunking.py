"""Split the policy documents into one chunk per numbered clause.

Both documents write clauses as `**2.1 Title.** body` (the primer uses `P1.1`), so each clause is
self-contained and keeps a stable ID that the agent cites and the API validates.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "pds"
DOCUMENTS = (
    ("pds", "ute-cover-pds.md"),  # binding policy terms
    ("primer", "how-motor-insurance-works.md"),  # background only, never cited for coverage
)

_CLAUSE = re.compile(r"^\*\*(P?\d+\.\d+)\s+(.+?)\*\*\s*(.*)$")
_SECTION = re.compile(r"^##\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_type: str
    clause_id: str
    title: str
    text: str  # full clause text, prefixed with its ID and title


def chunk_markdown(markdown: str, doc_type: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = ""
    for line in markdown.splitlines():
        line = line.strip()
        if m := _SECTION.match(line):
            section = m.group(1).strip()
            continue
        if m := _CLAUSE.match(line):
            clause_id, title, body = m.group(1), m.group(2).strip().rstrip("."), m.group(3).strip()
            text = f"Clause {clause_id} ({section}) {title}. {body}".strip()
            chunks.append(Chunk(f"{doc_type}:{clause_id}", doc_type, clause_id, title, text))
    return chunks


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc_type, filename in DOCUMENTS:
        chunks.extend(chunk_markdown((docs_dir / filename).read_text(encoding="utf-8"), doc_type))
    return chunks


def docs_version(docs_dir: Path = DOCS_DIR) -> str:
    """Short hash of the document text, recorded on every result so decisions can be traced to a PDS version."""
    digest = hashlib.sha256()
    for _, filename in DOCUMENTS:
        digest.update((docs_dir / filename).read_bytes())
    return digest.hexdigest()[:10]

"""Build the LanceDB index from docs/pds/*.md.

    python -m agent_api.index_build [index_dir]

Run at Docker image build time (and locally for development). The output folder is read-only at runtime.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent_api.chunking import docs_version, load_chunks
from agent_api.retrieval import EMBED_MODEL, INDEX_DIR, TABLE, embed_texts


def build(index_dir: Path = INDEX_DIR, embedder=None) -> int:
    import lancedb

    chunks = load_chunks()
    vectors = embed_texts([c.text for c in chunks], embedder)
    rows = [
        {
            "chunk_id": c.chunk_id, "doc_type": c.doc_type, "clause_id": c.clause_id,
            "title": c.title, "text": c.text, "vector": v,
        }
        for c, v in zip(chunks, vectors, strict=True)
    ]
    index_dir.mkdir(parents=True, exist_ok=True)
    lancedb.connect(str(index_dir)).create_table(TABLE, data=rows, mode="overwrite")
    (index_dir / "meta.json").write_text(json.dumps({
        "docs_version": docs_version(),
        "embed_model": EMBED_MODEL,
        "chunks": len(rows),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }), encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else INDEX_DIR
    print(f"indexed {build(target)} chunks into {target}")

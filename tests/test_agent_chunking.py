from agent_api.chunking import chunk_markdown, docs_version, load_chunks


def test_every_pds_clause_in_the_rules_is_chunked():
    ids = {c.clause_id for c in load_chunks() if c.doc_type == "pds"}
    # The clauses the decision order in clause 7.1 relies on must exist as retrievable chunks.
    assert {"2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "4.3", "4.4", "5.1", "6.1", "7.1"} <= ids


def test_primer_clauses_are_marked_as_background():
    primer = [c for c in load_chunks() if c.doc_type == "primer"]
    assert primer and all(c.clause_id.startswith("P") for c in primer)


def test_pds_covers_the_agreed_vehicles():
    text = {c.clause_id: c.text for c in load_chunks() if c.doc_type == "pds"}["2.1"]
    assert "UTE" in text and "BUS" in text and "STNWG" in text


def test_chunk_ids_are_unique():
    ids = [c.chunk_id for c in load_chunks()]
    assert len(ids) == len(set(ids))


def test_chunk_markdown_reads_section_title_and_body():
    chunk = chunk_markdown("## 2. Eligibility\n\n**2.1 Covered vehicles** (`VEH_BODY`). Only utes.", "pds")[0]
    assert chunk.clause_id == "2.1" and chunk.title == "Covered vehicles" and "Only utes" in chunk.text


def test_docs_version_is_stable():
    assert docs_version() == docs_version() and len(docs_version()) == 10

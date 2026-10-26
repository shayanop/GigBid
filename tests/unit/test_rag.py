import json
import shutil

from evals.runners.rag_eval import mrr, ndcg_at_k, rank_projects, recall_at_k
from rag import retriever
from rag.index.vector import build_index
from rag.ingest.loaders import fixed_chunks, load_persona
from rag.schema import Document


def test_load_persona_reads_every_format_with_metadata():
    docs = load_persona(retriever.PERSONAS_DIR / "fr_da")
    by_type = {t: [d for d in docs if d.type == t] for t in {d.type for d in docs}}
    assert len(by_type["cv"]) == 1 and "Mei Lin" in by_type["cv"][0].text
    assert len(by_type["case_study"]) == 20
    assert all(d.date and d.client_industry for d in by_type["case_study"])
    assert len(by_type["proposal"]) == 150
    assert {d.outcome for d in by_type["proposal"]} == {"won", "replied", "ignored"}
    assert by_type["code"] and by_type["repo_readme"] and by_type["review"]


def test_fixed_chunks_overlap_and_skill_tags():
    doc = Document(id="d", persona="p", type="case_study", source="x.md", project="p1",
                   text="Built with dbt and Snowflake. " * 40)
    chunks = fixed_chunks(doc, size=300, overlap=50)
    assert all(len(c.text) <= 300 for c in chunks)
    assert chunks[0].text[-50:] == chunks[1].text[:50]
    assert chunks[0].project == "p1" and set(chunks[0].skills) == {"dbt", "Snowflake"}


def test_index_rebuild_embeds_only_changed_documents(tmp_path, offline_rag):
    persona = tmp_path / "fr_ml"
    shutil.copytree(retriever.PERSONAS_DIR / "fr_ml", persona)
    index_dir, manifest = tmp_path / "index", tmp_path / "index" / "manifest.json"

    def build():
        return build_index(persona, index_dir, offline_rag,
                           lambda d: fixed_chunks(d, 800, 100), "fixed-800-100")

    first = build()
    assert json.loads(manifest.read_text())["embedded_chunks"] == len(first.chunks)
    assert json.loads((build(), manifest.read_text())[1])["embedded_chunks"] == 0

    case = persona / "case_studies" / "fr_ml-p01.md"
    case.write_text(case.read_text() + "\nAlso added Kubernetes autoscaling.\n")
    (persona / "case_studies" / "fr_ml-p02.md").unlink()
    third = build()
    assert json.loads(manifest.read_text())["embedded_chunks"] == len(
        [c for c in third.chunks if c.doc_id == "fr_ml-p01"])
    assert not [c for c in third.chunks if c.doc_id == "fr_ml-p02"]


def test_search_filters_and_ranks(offline_rag):
    index = retriever.build_retriever("fr_fs", "v0", offline_rag)
    hits = index.search("Stripe subscription billing", k=3, where=lambda c: c.type == "proposal")
    assert len(hits) == 3 and all(h.type == "proposal" for h in hits)
    assert hits[0].score >= hits[-1].score


def test_retrieval_metrics():
    relevant = {"a": 2, "b": 1}
    assert recall_at_k(["x", "a", "y", "z", "w", "b"], relevant, 5) == 0.5
    assert recall_at_k(["a", "b"], relevant, 5) == 1.0  # capped at |relevant|
    assert mrr(["x", "y", "b"], relevant) == 1 / 3 and mrr(["x"], relevant) == 0
    assert ndcg_at_k(["a", "b"], relevant, 10) == 1.0
    assert 0 < ndcg_at_k(["b", "a"], relevant, 10) < 1
    hits = [type("E", (), {"project": p})() for p in ["a", None, "a", "b"]]
    assert rank_projects(hits) == ["a", "b"]


def test_drop_sentences_matches_loosely_and_keeps_paragraphs():
    from agent.nodes.common import drop_sentences
    text = ("I built a Celery queue [p1#0]. I have 15 years of Rust [p9#0].\n\n"
            "Next step: a short call.")
    out = drop_sentences(text, ["I have 15 years of Rust experience", "15 years of Rust"])
    assert out == "I built a Celery queue [p1#0].\n\nNext step: a short call."


def test_citations_never_reach_the_client():
    from agent.graphs.bid_graph import client_text
    letter = ("I built it [fr_ml-p09#0]. Async endpoints ([fr_ml-p11/app.py#0], "
              "[fr_ml-p12/app.py#0]) and LangGraph [fr_ml-prop001#0], done.")
    assert client_text(letter) == "I built it. Async endpoints and LangGraph, done."

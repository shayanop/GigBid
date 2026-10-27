"""Retrieval components on a tiny hand-made index."""

import re

import numpy as np

from rag.index.vector import VectorIndex
from rag.pipeline import Components, Pipeline, fuse, requirements
from rag.schema import Chunk


class BlindEmbedder:
    """Every text gets the same vector, so dense ranking carries no signal."""
    name = "blind"

    def embed_documents(self, texts):
        return np.ones((len(texts), 4), np.float32) / 2

    def embed_query(self, text):
        return np.ones(4, np.float32) / 2


class OverlapGrader:
    """Stand-in cross-encoder: shared words minus a constant, so unrelated text grades < 0."""
    def score(self, query, texts):
        words = set(re.findall(r"\w+", query.lower()))
        return [len(words & set(re.findall(r"\w+", t.lower()))) - 1.5 for t in texts]


def index(*rows) -> VectorIndex:
    chunks = [Chunk(id=f"c{i}", doc_id=f"d{i}", persona="p", type=t, source="s", project=f"p{i}",
                    outcome=o, text=text, skills=[]) for i, (t, text, o) in enumerate(rows)]
    return VectorIndex(chunks, BlindEmbedder().embed_documents([c.text for c in chunks]),
                       BlindEmbedder())


def test_requirements_splits_listed_skills_and_sentences():
    post = "Build a queue. Must have experience with Celery, Redis and Django. We need it to scale well."
    assert requirements(post) == ["Celery", "Redis", "Django", "We need it to scale well."]


def test_fusion_rewards_agreement():
    scores = fuse([[1, 2, 3], [3, 1, 2]])
    assert max(scores, key=scores.get) == 1 and scores[3] > scores[2]


class MisleadingEmbedder:
    """Dense search confidently prefers the first document, whatever the query says."""
    name = "misleading"

    def embed_documents(self, texts):
        return np.array([[1.0, 0.0]] + [[0.6, 0.8]] * (len(texts) - 1), np.float32)

    def embed_query(self, text):
        return np.array([1.0, 0.0], np.float32)


def test_hybrid_finds_the_exact_technology_dense_search_misses():
    texts = ["React dashboard with charts", "Nightly Celery worker", "Stripe billing pages"]
    chunks = index(*[("code", t, None) for t in texts]).chunks
    idx = VectorIndex(chunks, MisleadingEmbedder().embed_documents(texts), MisleadingEmbedder())
    plain = Pipeline(idx, Components()).search("Celery task queue", k=1)
    hybrid = Pipeline(idx, Components(hybrid=True)).search("Celery task queue", k=1)
    assert plain[0].text == "React dashboard with charts"
    assert hybrid[0].text == "Nightly Celery worker"


def test_outcome_boost_prefers_winning_proposals():
    idx = index(("proposal", "RAG chatbot proposal", "ignored"), ("proposal", "RAG chatbot proposal", "won"))
    top = Pipeline(idx, Components(hybrid=True, outcome=True)).search("RAG chatbot", k=1)[0]
    assert top.outcome == "won"


def test_rerank_orders_by_the_grader():
    idx = index(("code", "billing", None), ("code", "Celery queue retries", None))
    top = Pipeline(idx, Components(rerank=True), OverlapGrader()).search("Celery queue retries", k=2)
    assert top[0].text == "Celery queue retries" and top[0].score > top[1].score


def test_corrective_drops_evidence_that_fails_the_grade():
    idx = index(("code", "Stripe billing pages", None), ("code", "Celery queue with retries", None))
    grader = OverlapGrader()
    hits = Pipeline(idx, Components(corrective=True), grader).search("Celery queue", k=5)
    assert [h.text for h in hits] == ["Celery queue with retries"]
    assert Pipeline(idx, Components(corrective=True), grader).search("Kubernetes operator", k=5) == []


def test_weighted_kappa():
    from evals.runners.judge_calibration import weighted_kappa
    assert weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert weighted_kappa([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    # Near misses cost less than far misses.
    near = weighted_kappa([1, 2, 3, 4, 5, 3], [1, 2, 3, 4, 5, 4])
    far = weighted_kappa([1, 2, 3, 4, 5, 3], [1, 2, 3, 4, 5, 1])
    assert 0 < far < near < 1

"""Composable retrieval over the V0 index (B2). Each component is one idea from the spec's
variant table, switched on independently, so variants, the selected pipeline and its
ablations are all the same code with different flags:

- decompose  (V1): also search each requirement in the post, merge with reciprocal rank fusion
- hybrid     (V2): BM25 keyword ranking fused with the dense ranking
- rerank     (V3): a cross-encoder rescores the top candidates against the full post
- outcome    (V4): proposals that won or got replies, and their projects, rank higher
- corrective (V8): the cross-encoder grades evidence; weak requirements are searched again,
                   and evidence below the grade threshold is dropped rather than returned
"""

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, fields
from functools import cache

import bm25s
import numpy as np

from rag.index.vector import VectorIndex
from rag.schema import Chunk, Evidence

RRF_K = 60  # standard reciprocal-rank-fusion constant
CANDIDATES = 30  # how many candidates the cross-encoder sees
OUTCOME_BOOST = {"won": 0.5, "replied": 0.2, "ignored": -0.2}


@dataclass(frozen=True)
class Components:
    decompose: bool = False
    hybrid: bool = False
    rerank: bool = False
    outcome: bool = False
    corrective: bool = False

    def on(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name)]


class CrossEncoder:
    """Open cross-encoder on CPU (fastembed). score() returns one relevance logit per text."""

    def __init__(self, model: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.name, self._model = model, TextCrossEncoder(model)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return list(self._model.rerank(query, texts))


@cache
def cross_encoder(model: str) -> CrossEncoder:
    return CrossEncoder(model)


def requirements(query: str) -> list[str]:
    """Requirement phrases in a job post: listed skills, then substantive sentences."""
    skills = [s.strip() for m in re.finditer(r"experience (?:with|in) ([^.\n]+)", query, re.IGNORECASE)
              for s in re.split(r",|\band\b", m.group(1)) if s.strip()]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", query)
                 if len(s.split()) >= 4 and "experience with" not in s.lower()]
    return list(dict.fromkeys(skills + sentences))[:12]


def fuse(rankings: list[list[int]]) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, i in enumerate(ranking):
            scores[i] += 1 / (RRF_K + rank + 1)
    return scores


class Pipeline:
    def __init__(self, index: VectorIndex, components: Components, grader: CrossEncoder | None = None,
                 threshold: float = 0.0):
        self.index, self.c, self.threshold = index, components, threshold
        self.chunks = index.chunks
        self.grader = grader
        if components.hybrid and self.chunks:
            self.bm25 = bm25s.BM25()
            self.bm25.index(bm25s.tokenize([c.text for c in self.chunks], stopwords="en",
                                           show_progress=False), show_progress=False)
        if components.outcome:
            self.boost = self._outcome_boosts()

    def _outcome_boosts(self) -> list[float]:
        """Proposals by their outcome; projects by how their proposals did."""
        per_project: dict[str, float] = defaultdict(float)
        for c in self.chunks:
            if c.type == "proposal" and c.project and c.outcome:
                per_project[c.project] += OUTCOME_BOOST[c.outcome] / 10
        return [OUTCOME_BOOST.get(c.outcome, 0.0) if c.type == "proposal"
                else max(-0.2, min(0.5, per_project[c.project])) if c.project else 0.0
                for c in self.chunks]

    def _scores(self, query: str) -> dict[int, float]:
        """Top 100 chunks for one query: cosine scores, or fused dense+BM25 scores."""
        sims = self.index.vectors @ self.index.embedder.embed_query(query)
        dense = np.argsort(-sims).tolist()
        if not self.c.hybrid:
            return {i: float(sims[i]) for i in dense[:100]}
        ids, _ = self.bm25.retrieve(bm25s.tokenize(query, stopwords="en", show_progress=False),
                                    k=len(self.chunks), show_progress=False)
        fused = fuse([dense, ids[0].tolist()])
        return dict(sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:100])

    def _ranking(self, query: str) -> list[int]:
        scores = self._scores(query)
        return sorted(scores, key=scores.get, reverse=True)

    def _scored(self, query: str) -> dict[int, float]:
        if not self.c.decompose:
            return self._scores(query)
        return fuse([self._ranking(q) for q in [query, *requirements(query)]])

    def search(self, query: str, k: int = 5,
               where: Callable[[Chunk], bool] | None = None) -> list[Evidence]:
        if not self.chunks:
            return []
        scores = {i: s for i, s in self._scored(query).items()
                  if where is None or where(self.chunks[i])}
        if self.c.outcome:  # rank-preserving bonus, scaled to the score range
            # Tied scores still need the bonus to break the tie.
            spread = ((max(scores.values()) - min(scores.values())) if scores else 0) or 1.0
            scores = {i: s + self.boost[i] * spread for i, s in scores.items()}
        order = sorted(scores, key=scores.get, reverse=True)
        if self.c.rerank or self.c.corrective:
            top = order[:max(CANDIDATES, k)]
            graded = dict(zip(top, self.grader.score(query, [self.chunks[i].text for i in top]),
                              strict=True))
            if self.c.corrective:
                graded = self._correct(query, graded, where)
            order = sorted(graded, key=graded.get, reverse=True)
            scores = graded
        return [Evidence(**self.chunks[i].model_dump(), score=float(scores[i])) for i in order[:k]]

    def _correct(self, query: str, graded: dict[int, float],
                 where: Callable[[Chunk], bool] | None) -> dict[int, float]:
        """Re-search each requirement the graded evidence does not cover, then drop
        everything below the threshold: no evidence beats wrong evidence."""
        best = sorted(graded, key=graded.get, reverse=True)[:10]
        for requirement in requirements(query)[:6]:  # listed skills come first
            covered = max(self.grader.score(requirement, [self.chunks[i].text for i in best]),
                          default=-1e9)
            if covered >= self.threshold:
                continue
            extra = [i for i in self._ranking(requirement)[:10]
                     if i not in graded and (where is None or where(self.chunks[i]))]
            if extra:
                graded |= dict(zip(extra, self.grader.score(
                    query, [self.chunks[i].text for i in extra]), strict=True))
        return {i: s for i, s in graded.items() if s >= self.threshold}

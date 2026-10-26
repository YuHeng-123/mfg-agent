"""BM25 over three fields, then a model hard filter, then optional RRF.

Design notes that we have to be able to defend in an interview:

1. Field weighting is done by scoring each field with its own BM25 statistics and
   summing the weighted scores, not by duplicating tokens. Duplicating tokens
   corrupts IDF; separating fields keeps every number explainable per field.
2. `max_possible(query)` returns the score a hypothetical document would get if
   it contained every query term at full saturation. The evidence gate divides
   by it, which makes the threshold corpus-size independent.
3. The model filter runs BEFORE scoring, not after. Filtering afterwards would
   let a chunk from the wrong model outrank the right one and then get dropped,
   leaving an empty result set even though a good answer existed.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from core.rag.tokenize import tokenize
from core.types import Chunk


@dataclass
class Hit:
    chunk: Chunk
    score: float
    parts: dict[str, float] = field(default_factory=dict)


class BM25Field:
    """BM25 over one field of a fixed document set."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.tfs: list[Counter[str]] = [Counter(d) for d in docs]
        self.lens: list[int] = [len(d) for d in docs]
        self.avgdl: float = (sum(self.lens) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        self.idf: dict[str, float] = {
            t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }
        # idf of a term that never occurs. Used only by max_possible(): a query
        # made of words the corpus has never seen must score LOW confidence,
        # which only works if unseen terms enlarge the denominator.
        self.unseen_idf: float = math.log(1 + (self.n + 0.5) / 0.5)

    def score(self, q_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.n
        if not self.n or not self.avgdl:
            return scores
        for term in dict.fromkeys(q_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tfs):
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avgdl)
                scores[i] += idf * f * (self.k1 + 1) / denom
        return scores

    def max_possible(self, q_tokens: list[str]) -> float:
        """Upper bound of what any document could score for this query.

        Unknown terms count at `unseen_idf`, so a question whose words barely
        appear in the corpus gets a large denominator and therefore a low
        normalised score. That is what makes the evidence gate meaningful:
        it measures how much of the question the corpus actually covers.
        """

        total = 0.0
        for term in dict.fromkeys(q_tokens):
            total += self.idf.get(term, self.unseen_idf) * (self.k1 + 1)
        return total


FIELD_WEIGHTS = {"body": 1.0, "section": 1.8, "title": 1.5}


@dataclass
class QueryStats:
    """How much of the question the corpus can actually speak to.

    Measured by counting matched *distinct* terms and summing their IDF, not by
    a score ratio. Rationale (learned from the first test run): a ratio against a
    theoretical maximum punishes conversational filler ("怎么处理"), while a count
    plus an IDF mass cleanly separates "we have material" from "we only matched
    one incidental word". Both numbers are corpus-size independent and trivially
    explainable to a non-ML reader.
    """

    total_terms: int
    matched_terms: int
    matched_mass: float
    terms: list[str] = field(default_factory=list)


class Index:
    """Retrieval over Chunk objects with a mandatory metadata filter hook."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.body = BM25Field([tokenize(c.text) for c in chunks])
        self.section = BM25Field([tokenize(c.section or "") for c in chunks])
        self.title = BM25Field([tokenize(c.doc_title) for c in chunks])

    # ---- public API -----------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        model_id: str | None = None,
        model_ids: list[str] | None = None,
        doc_type: str | None = None,
    ) -> list[Hit]:
        allowed = self._allowed(model_id=model_id, model_ids=model_ids, doc_type=doc_type)
        if not allowed:
            return []
        q = tokenize(query)
        if not q:
            return []

        body = self.body.score(q)
        section = self.section.score(q)
        title = self.title.score(q)

        hits: list[Hit] = []
        for i in allowed:
            score = (
                FIELD_WEIGHTS["body"] * body[i]
                + FIELD_WEIGHTS["section"] * section[i]
                + FIELD_WEIGHTS["title"] * title[i]
            )
            if score <= 0:
                continue
            hits.append(
                Hit(
                    chunk=self.chunks[i],
                    score=score,
                    parts={
                        "body": round(body[i], 4),
                        "section": round(section[i], 4),
                        "title": round(title[i], 4),
                    },
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def max_possible(self, query: str) -> float:
        q = tokenize(query)
        return (
            FIELD_WEIGHTS["body"] * self.body.max_possible(q)
            + FIELD_WEIGHTS["section"] * self.section.max_possible(q)
            + FIELD_WEIGHTS["title"] * self.title.max_possible(q)
        )

    def normalised_top1(self, query: str, hits: list[Hit]) -> float:
        """0..1 confidence proxy used for display only, not for the gate.

        Dividing by `max_possible` (which charges every unseen term at max IDF)
        keeps long chatty questions from looking confident, but it moves with
        query phrasing, so the gate uses `query_stats` instead.
        """

        mp = self.max_possible(query)
        if not hits or mp <= 0:
            return 0.0
        return min(1.0, hits[0].score / mp)

    def query_stats(self, query: str) -> QueryStats:
        toks = list(dict.fromkeys(tokenize(query)))
        matched = {t: self.body.idf[t] for t in toks if t in self.body.idf}
        return QueryStats(
            total_terms=len(toks),
            matched_terms=len(matched),
            matched_mass=round(sum(matched.values()), 4),
            terms=sorted(matched),
        )

    # ---- internals ------------------------------------------------------

    def _allowed(
        self, *, model_id: str | None, model_ids: list[str] | None, doc_type: str | None
    ) -> list[int]:
        wanted = set(model_ids) if model_ids else ({model_id} if model_id else None)
        idx: list[int] = []
        for i, c in enumerate(self.chunks):
            if wanted and c.meta.get("model_id") not in wanted | {None}:
                continue
            if doc_type and c.meta.get("doc_type") != doc_type:
                continue
            idx.append(i)
        return idx


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion over several id rankings."""

    acc: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            acc[doc_id] = acc.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(acc.items(), key=lambda kv: kv[1], reverse=True)

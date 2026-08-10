from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import Citation, Policy, RetrievedEvidence


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_.%-]+", lowered)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    chinese: list[str] = []
    for run in chinese_runs:
        chinese.extend(list(run))
        chinese.extend(run[i : i + 2] for i in range(len(run) - 1))
    return latin + chinese


@dataclass
class EvidenceChunk:
    text: str
    citation: Citation


class CitationRetriever:
    """Small dependency-free BM25 retriever for the curated public-policy corpus."""

    def __init__(self, policies: list[Policy], extra_chunks=None) -> None:
        self.chunks: list[EvidenceChunk] = []
        for policy in policies:
            for citation in policy.sources:
                self.chunks.append(EvidenceChunk(citation.quote, citation))
            for rule in policy.rules:
                for citation in rule.citations:
                    self.chunks.append(EvidenceChunk(f"{rule.label}。{citation.quote}", citation))
            for material in policy.materials:
                for citation in material.citations:
                    self.chunks.append(EvidenceChunk(f"{material.label}。{citation.quote}", citation))
        for chunk in extra_chunks or []:
            self.chunks.append(EvidenceChunk(chunk.text, chunk.citation))
        self.tokens = [tokenize(chunk.text) for chunk in self.chunks]
        self.doc_freq = Counter(token for doc in self.tokens for token in set(doc))
        self.avg_len = sum(map(len, self.tokens)) / max(len(self.tokens), 1)

    def search(self, query: str, top_k: int = 5) -> list[RetrievedEvidence]:
        query_tokens = tokenize(query)
        scores: list[tuple[float, int]] = []
        corpus_size = max(len(self.tokens), 1)
        for index, doc in enumerate(self.tokens):
            frequencies = Counter(doc)
            score = 0.0
            for token in query_tokens:
                df = self.doc_freq.get(token, 0)
                if not df:
                    continue
                idf = math.log(1 + (corpus_size - df + 0.5) / (df + 0.5))
                tf = frequencies[token]
                denominator = tf + 1.5 * (1 - 0.75 + 0.75 * len(doc) / max(self.avg_len, 1))
                score += idf * tf * 2.5 / denominator
            if score > 0:
                scores.append((score, index))
        scores.sort(reverse=True)
        return [
            RetrievedEvidence(
                text=self.chunks[index].text,
                score=round(score, 4),
                citation=self.chunks[index].citation.model_dump(),
            )
            for score, index in scores[:top_k]
        ]


class HybridCitationRetriever(CitationRetriever):
    """BM25 + character n-gram TF-IDF + exact numeric/phrase reranking."""

    def __init__(
        self,
        policies: list[Policy],
        extra_chunks=None,
        bm25_weight: float = 0.55,
        semantic_weight: float = 0.35,
        exact_weight: float = 0.10,
    ) -> None:
        super().__init__(policies, extra_chunks=extra_chunks)
        self.bm25_weight = bm25_weight
        self.semantic_weight = semantic_weight
        self.exact_weight = exact_weight
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
        corpus = [chunk.text for chunk in self.chunks]
        self.matrix = self.vectorizer.fit_transform(corpus) if corpus else None

    def search(self, query: str, top_k: int = 5) -> list[RetrievedEvidence]:
        if not query.strip() or not self.chunks:
            return []
        bm25_results = super().search(query, top_k=len(self.chunks))
        bm25_by_key = {
            (item.citation.source_id, item.citation.locator, item.text): item.score
            for item in bm25_results
        }
        max_bm25 = max(bm25_by_key.values(), default=1.0)
        semantic = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        query_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", query))
        query_terms = set(tokenize(query))
        ranked: list[tuple[float, int]] = []
        for index, chunk in enumerate(self.chunks):
            key = (chunk.citation.source_id, chunk.citation.locator, chunk.text)
            bm25 = bm25_by_key.get(key, 0.0) / max_bm25
            semantic_score = float(semantic[index])
            chunk_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", chunk.text))
            number_match = len(query_numbers & chunk_numbers) / max(len(query_numbers), 1)
            phrase_match = 1.0 if query.strip().lower() in chunk.text.lower() else 0.0
            token_overlap = len(query_terms & set(tokenize(chunk.text))) / max(len(query_terms), 1)
            exact = max(number_match, phrase_match, token_overlap)
            official_boost = 0.02 if chunk.citation.official else 0.0
            score = (
                self.bm25_weight * bm25
                + self.semantic_weight * semantic_score
                + self.exact_weight * exact
                + official_boost
            )
            if score > 0.01:
                ranked.append((score, index))
        ranked.sort(key=lambda item: (item[0], self.chunks[item[1]].citation.official), reverse=True)

        output: list[RetrievedEvidence] = []
        seen: set[tuple[str, str, str]] = set()
        for score, index in ranked:
            chunk = self.chunks[index]
            key = (chunk.citation.source_id, chunk.citation.locator, chunk.text)
            if key in seen:
                continue
            seen.add(key)
            output.append(
                RetrievedEvidence(
                    text=chunk.text,
                    score=round(score, 4),
                    citation=chunk.citation.model_dump(),
                )
            )
            if len(output) >= top_k:
                break
        return output

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

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
                citation=self.chunks[index].citation,
            )
            for score, index in scores[:top_k]
        ]

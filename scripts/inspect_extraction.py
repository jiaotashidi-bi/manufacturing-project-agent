from __future__ import annotations

from collections import Counter

from manufacturing_agent.extraction import extract_candidates
from manufacturing_agent.ingestion import SourceIngestor
from manufacturing_agent.repository import project_root


def main() -> None:
    ingestor = SourceIngestor(project_root())
    candidates = []
    for chunk in ingestor.chunks():
        candidates.extend(extract_candidates(chunk.text))
    counts = Counter(item.kind for item in candidates)
    print("抽取候选统计：", dict(counts))
    for candidate in candidates[:80]:
        print(f"[{candidate.kind}] {candidate.value} | {candidate.context}")
    print("\n注意：候选仅用于辅助校对，正式规则必须保留人工复核和来源定位。")


if __name__ == "__main__":
    main()

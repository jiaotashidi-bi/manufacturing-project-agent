from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionCandidate:
    kind: str
    value: str
    context: str


PATTERNS = {
    "date": re.compile(r"20\d{2}年\d{1,2}月\d{1,2}日"),
    "amount": re.compile(r"\d+(?:\.\d+)?\s*(?:万元|亿元|元)"),
    "percentage": re.compile(r"\d+(?:\.\d+)?%"),
    "threshold": re.compile(
        r"[^。；]{0,45}(?:不低于|不超过|达到|以上|以下)[^。；]{0,45}[。；]?"
    ),
    "material": re.compile(r"[^。；]{0,30}(?:材料|申请书|承诺书|审计报告)[^。；]{0,30}[。；]?"),
}


def extract_candidates(text: str, context_radius: int = 35) -> list[ExtractionCandidate]:
    """Extract review candidates; policy JSON remains human-reviewed and authoritative."""
    candidates: list[ExtractionCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            start = max(0, match.start() - context_radius)
            end = min(len(text), match.end() + context_radius)
            candidate = (kind, match.group().strip(), text[start:end].strip())
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(ExtractionCandidate(*candidate))
    return candidates

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CompanyProfile, Policy


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Repository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_root()
        self.policy_dir = self.root / "data" / "policies"
        self.company_dir = self.root / "data" / "companies"

    @staticmethod
    def _load_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def list_policies(self) -> list[Policy]:
        return [
            Policy.model_validate(self._load_json(path))
            for path in sorted(self.policy_dir.glob("*.json"))
        ]

    def list_companies(self) -> list[CompanyProfile]:
        return [
            CompanyProfile.model_validate(self._load_json(path))
            for path in sorted(self.company_dir.glob("*.json"))
        ]

    def get_policy(self, policy_id: str) -> Policy:
        return self._find(self.list_policies(), policy_id, "policy")

    def get_company(self, company_id: str) -> CompanyProfile:
        return self._find(self.list_companies(), company_id, "company")

    def source_chunks(self):
        from .ingestion import SourceIngestor, load_index

        path = self.root / "data" / "index" / "source_chunks.jsonl"
        chunks = load_index(path)
        if not chunks:
            SourceIngestor(self.root).build_index(path)
            chunks = load_index(path)
        return chunks

    @staticmethod
    def _find(items: Iterable, target_id: str, kind: str):
        for item in items:
            if item.id == target_id:
                return item
        raise KeyError(f"Unknown {kind}: {target_id}")

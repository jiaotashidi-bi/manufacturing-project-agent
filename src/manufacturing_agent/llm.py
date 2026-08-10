from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import httpx

from .config import AppSettings
from .extraction import extract_candidates

SYSTEM_PROMPT = """你是制造业公开政策抽取助手。只抽取原文明确陈述的事实，不推断企业资格。
输出必须是单个 JSON 对象，字段为 title、issuer、document_number、published_at、
application_start、application_deadline、amount_note、program_level、summary、tags、
rules、materials。无法确定时使用 null 或空数组；每条规则和材料必须包含原文 quote 与 locator。
不得编造金额、日期、申报条件或材料。"""


class StructuredPolicyProvider(ABC):
    name: str

    @abstractmethod
    def extract(self, text: str, source: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OfflineStructuredProvider(StructuredPolicyProvider):
    name = "offline-regex"

    def extract(self, text: str, source: dict[str, Any]) -> dict[str, Any]:
        candidates = extract_candidates(text)
        return {
            "title": source.get("title") or "待审核政策",
            "issuer": source.get("issuer") or "待人工确认",
            "document_number": None,
            "published_at": date.today().isoformat(),
            "application_start": None,
            "application_deadline": None,
            "amount_note": "金额待人工确认",
            "program_level": "待人工确认",
            "summary": "离线抽取已生成候选项，所有字段须经人工审核。",
            "tags": sorted({candidate.kind for candidate in candidates}),
            "rules": [
                {
                    "kind": candidate.kind,
                    "value": candidate.value,
                    "quote": candidate.context,
                    "locator": source.get("locator", "上传文件"),
                    "confidence": 0.55,
                }
                for candidate in candidates
                if candidate.kind in {"threshold", "percentage"}
            ],
            "materials": [
                {
                    "label": candidate.value[:80],
                    "quote": candidate.context,
                    "locator": source.get("locator", "上传文件"),
                    "confidence": 0.55,
                }
                for candidate in candidates
                if candidate.kind == "material"
            ],
            "candidates": [candidate.__dict__ for candidate in candidates],
        }


class OpenAICompatibleProvider(StructuredPolicyProvider):
    name = "openai-compatible"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def extract(self, text: str, source: dict[str, Any]) -> dict[str, Any]:
        key = self.settings.llm_api_key
        if key is None:
            raise RuntimeError("LLM API key is not configured")
        schema_hint = {
            "title": "string",
            "issuer": "string",
            "document_number": "string|null",
            "published_at": "YYYY-MM-DD|null",
            "application_start": "YYYY-MM-DD|null",
            "application_deadline": "YYYY-MM-DD|null",
            "amount_note": "string",
            "program_level": "string",
            "summary": "string",
            "tags": ["string"],
            "rules": [
                {
                    "label": "string",
                    "fact": "string",
                    "operator": "eq|gte|lte|gt|lt|in|contains|all_true|any_true",
                    "expected": "JSON value",
                    "unit": "string|null",
                    "quote": "string",
                    "locator": "string",
                    "confidence": 0.0,
                }
            ],
            "materials": [
                {
                    "label": "string",
                    "description": "string",
                    "required": True,
                    "quote": "string",
                    "locator": "string",
                    "confidence": 0.0,
                }
            ],
        }
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"来源元数据：{json.dumps(source, ensure_ascii=False)}\n"
                        f"目标结构：{json.dumps(schema_hint, ensure_ascii=False)}\n"
                        f"政策原文：\n{text[:120000]}"
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key.get_secret_value()}"},
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object")
        return result


def build_provider(settings: AppSettings) -> StructuredPolicyProvider:
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    return OfflineStructuredProvider()

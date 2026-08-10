from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from docx import Document
from pypdf import PdfReader

from .config import AppSettings
from .database import DatabaseStore
from .llm import StructuredPolicyProvider, build_provider
from .models import (
    Citation,
    ExtractedPolicyField,
    MaterialRequirement,
    Policy,
    PolicyExtractionDraft,
    Rule,
)
from .upload_security import detect_sensitive_text, inspect_upload, safe_filename


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class PolicyIntakeService:
    def __init__(
        self,
        settings: AppSettings,
        database: DatabaseStore,
        provider: StructuredPolicyProvider | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.provider = provider or build_provider(settings)

    @staticmethod
    def _read_text(filename: str, content: bytes) -> tuple[str, list[tuple[str, str]]]:
        suffix = Path(filename).suffix.lower()
        locators: list[tuple[str, str]] = []
        with NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            if suffix == ".pdf":
                for number, page in enumerate(PdfReader(temp_path).pages, start=1):
                    page_text = (page.extract_text() or "").strip()
                    if page_text:
                        locators.append((f"第{number}页", page_text))
            else:
                document = Document(str(temp_path))
                for number, paragraph in enumerate(document.paragraphs, start=1):
                    text = paragraph.text.strip()
                    if text:
                        locators.append((f"段落{number}", text))
                for table_no, table in enumerate(document.tables, start=1):
                    for row_no, row in enumerate(table.rows, start=1):
                        text = " | ".join(cell.text.strip() for cell in row.cells)
                        if text.strip(" |"):
                            locators.append((f"表{table_no}第{row_no}行", text))
        finally:
            temp_path.unlink(missing_ok=True)
        return "\n".join(text for _, text in locators), locators

    def ingest(
        self,
        filename: str,
        content: bytes,
        source_url: str,
        actor: str,
        confirmed_public: bool,
        title: str | None = None,
        issuer: str | None = None,
    ) -> tuple[PolicyExtractionDraft, int]:
        if not confirmed_public:
            raise PermissionError("上传前必须确认文件属于公开政策资料且不含真实企业敏感数据")
        inspection = inspect_upload(filename, content, self.settings.upload_max_mb)
        if not inspection.safe:
            raise ValueError("；".join(inspection.warnings))
        text, located = self._read_text(filename, content)
        if not text:
            raise ValueError("未提取到文本；扫描件需要先执行 OCR")
        warnings = list(inspection.warnings)
        sensitive = detect_sensitive_text(text)
        if sensitive:
            warnings.append("检测到可能的敏感字段：" + "、".join(sensitive))

        file_hash = hashlib.sha256(content).hexdigest()
        source_id = f"upload-{file_hash[:12]}"
        source = {
            "source_id": source_id,
            "title": title or Path(safe_filename(filename)).stem,
            "issuer": issuer,
            "url": source_url,
            "locator": located[0][0] if located else "上传文件",
        }
        extracted = self.provider.extract(text, source)
        policy = self._to_policy(extracted, source, file_hash)
        fields = self._fields(extracted, policy)
        if self.provider.name == "offline-regex":
            warnings.append("当前使用离线候选抽取；日期、金额、条件和材料必须人工补全并批准")
        draft = PolicyExtractionDraft(
            policy=policy,
            extracted_fields=fields,
            warnings=warnings,
            provider=self.provider.name,
            source_sha256=file_hash,
        )
        version = self.database.save_policy_draft(policy, file_hash, actor)
        return draft, version

    def _to_policy(self, data: dict[str, Any], source: dict[str, Any], file_hash: str) -> Policy:
        title = str(data.get("title") or source["title"])
        citation_base = {
            "source_id": source["source_id"],
            "title": title,
            "url": source.get("url") or "about:blank",
            "official": True,
        }

        rules: list[Rule] = []
        for index, item in enumerate(data.get("rules") or [], start=1):
            if not all(key in item for key in ("label", "fact", "operator", "expected")):
                continue
            citation = Citation(
                **citation_base,
                locator=str(item.get("locator") or "上传文件"),
                quote=str(item.get("quote") or item["label"])[:500],
            )
            try:
                rules.append(
                    Rule(
                        id=f"rule_{index}",
                        label=str(item["label"]),
                        fact=str(item["fact"]),
                        operator=item["operator"],
                        expected=item["expected"],
                        unit=item.get("unit"),
                        explanation="模型抽取候选，待人工审核",
                        citations=[citation],
                    )
                )
            except ValueError:
                continue

        materials: list[MaterialRequirement] = []
        for index, item in enumerate(data.get("materials") or [], start=1):
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            citation = Citation(
                **citation_base,
                locator=str(item.get("locator") or "上传文件"),
                quote=str(item.get("quote") or label)[:500],
            )
            materials.append(
                MaterialRequirement(
                    id=f"material_{index}",
                    label=label,
                    description=str(item.get("description") or label),
                    required=bool(item.get("required", True)),
                    citations=[citation],
                )
            )

        root_citation = Citation(
            **citation_base,
            locator="上传文件",
            quote=str(data.get("summary") or title)[:500],
        )
        published_at = data.get("published_at") or date.today()
        return Policy(
            id=f"uploaded_{_slug(title)[:80]}_{file_hash[:8]}",
            title=title,
            issuer=str(data.get("issuer") or source.get("issuer") or "待人工确认"),
            document_number=data.get("document_number"),
            published_at=published_at,
            application_start=data.get("application_start"),
            application_deadline=data.get("application_deadline"),
            amount_cny=data.get("amount_cny"),
            amount_note=str(data.get("amount_note") or "金额待人工确认"),
            program_level=str(data.get("program_level") or "待人工确认"),
            summary=str(data.get("summary") or "政策抽取草稿，待人工审核"),
            sources=[root_citation],
            rules=rules,
            materials=materials,
            tags=[str(tag) for tag in data.get("tags") or []],
            application_url=source.get("url"),
        )

    @staticmethod
    def _fields(data: dict[str, Any], policy: Policy) -> list[ExtractedPolicyField]:
        confidence = 0.55 if data.get("candidates") is not None else 0.78
        return [
            ExtractedPolicyField(
                field=name,
                value=getattr(policy, name),
                confidence=confidence,
                citation=policy.sources[0],
            )
            for name in (
                "title",
                "issuer",
                "published_at",
                "application_start",
                "application_deadline",
                "amount_note",
            )
        ]

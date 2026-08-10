from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from docx import Document
from pypdf import PdfReader

from .models import Citation


@dataclass
class SourceChunk:
    text: str
    citation: Citation


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_text(text: str, max_chars: int = 450) -> list[str]:
    clean = normalize_text(text)
    if not clean:
        return []
    sentences = re.split(r"(?<=[。！？；])", clean)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= max_chars:
            current += sentence
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SourceIngestor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "data" / "sources.json"

    def manifest(self) -> list[dict]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _pdf_chunks(self, source: dict, path: Path) -> Iterator[SourceChunk]:
        for page_number, page in enumerate(PdfReader(path).pages, start=1):
            for text in split_text(page.extract_text() or ""):
                yield SourceChunk(
                    text=text,
                    citation=Citation(
                        source_id=source["source_id"],
                        title=source["title"],
                        url=source["url"],
                        locator=f"第{page_number}页",
                        quote=text[:120],
                        official=source.get("official", True),
                    ),
                )

    def _docx_chunks(self, source: dict, path: Path) -> Iterator[SourceChunk]:
        document = Document(path)
        block_number = 0
        for paragraph in document.paragraphs:
            for text in split_text(paragraph.text):
                block_number += 1
                yield SourceChunk(
                    text=text,
                    citation=Citation(
                        source_id=source["source_id"],
                        title=source["title"],
                        url=source["url"],
                        locator=f"正文块{block_number}",
                        quote=text[:120],
                        official=source.get("official", True),
                    ),
                )
        for table_number, table in enumerate(document.tables, start=1):
            for row_number, row in enumerate(table.rows, start=1):
                text = " | ".join(normalize_text(cell.text) for cell in row.cells)
                if not text.strip(" |"):
                    continue
                yield SourceChunk(
                    text=text,
                    citation=Citation(
                        source_id=source["source_id"],
                        title=source["title"],
                        url=source["url"],
                        locator=f"表{table_number}第{row_number}行",
                        quote=text[:120],
                        official=source.get("official", True),
                    ),
                )

    def chunks(self) -> Iterator[SourceChunk]:
        for source in self.manifest():
            path = self.root / source["path"]
            if not path.exists():
                raise FileNotFoundError(f"Source file missing: {path}")
            actual_hash = sha256_file(path)
            if source.get("sha256") and actual_hash != source["sha256"]:
                raise ValueError(f"Source hash mismatch: {path}")
            if source["kind"] == "pdf":
                yield from self._pdf_chunks(source, path)
            elif source["kind"] == "docx":
                yield from self._docx_chunks(source, path)
            else:
                raise ValueError(f"Unsupported source kind: {source['kind']}")

    def build_index(self, output: Path | None = None) -> tuple[Path, int]:
        output = output or self.root / "data" / "index" / "source_chunks.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with output.open("w", encoding="utf-8") as handle:
            for chunk in self.chunks():
                record = {
                    "text": chunk.text,
                    "citation": chunk.citation.model_dump(mode="json"),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        return output, count

    def inventory(self) -> list[dict]:
        inventory = []
        for source in self.manifest():
            path = self.root / source["path"]
            actual_hash = sha256_file(path)
            inventory.append(
                {
                    **source,
                    "bytes": path.stat().st_size,
                    "actual_sha256": actual_hash,
                    "hash_matches": not source.get("sha256") or source["sha256"] == actual_hash,
                }
            )
        return inventory


def load_index(path: Path) -> list[SourceChunk]:
    if not path.exists():
        return []
    chunks: list[SourceChunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        chunks.append(
            SourceChunk(
                text=record["text"],
                citation=Citation.model_validate(record["citation"]),
            )
        )
    return chunks

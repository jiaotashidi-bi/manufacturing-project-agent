from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAGIC = {".pdf": b"%PDF", ".docx": b"PK"}
SENSITIVE_PATTERNS = {
    "统一社会信用代码": re.compile(r"\b[0-9A-HJ-NPQRTUWXY]{18}\b"),
    "身份证号": re.compile(r"\b\d{17}[\dXx]\b"),
    "银行卡号": re.compile(r"\b\d{16,19}\b"),
    "手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "疑似密钥": re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{8,}"),
}


@dataclass
class UploadInspection:
    safe: bool
    extension: str
    warnings: list[str] = field(default_factory=list)


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", name)
    return cleaned[:160] or "upload"


def inspect_upload(filename: str, content: bytes, max_mb: int) -> UploadInspection:
    extension = Path(filename).suffix.lower()
    warnings: list[str] = []
    if extension not in ALLOWED_EXTENSIONS:
        return UploadInspection(False, extension, ["仅支持 PDF 或 DOCX 文件"])
    if len(content) > max_mb * 1024 * 1024:
        return UploadInspection(False, extension, [f"文件超过 {max_mb} MB 限制"])
    if not content.startswith(MAGIC[extension]):
        return UploadInspection(False, extension, ["文件签名与扩展名不一致"])
    if len(content) < 64:
        warnings.append("文件异常短，请人工确认")
    return UploadInspection(True, extension, warnings)


def detect_sensitive_text(text: str) -> list[str]:
    return [label for label, pattern in SENSITIVE_PATTERNS.items() if pattern.search(text)]

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import PolicyAssessment, RuleStatus, WorkflowRun

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
NAVY = "0B2545"
MUTED = "5E6B78"
LIGHT_FILL = "F4F6F9"
RISK = "9B1C1C"
GREEN = "1F5C45"
TABLE_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120


def _set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def _set_table_geometry(table, widths: list[int]) -> None:
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(TABLE_INDENT_DXA))
    tbl_ind.set(qn("w:type"), "dxa")

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row_index, row in enumerate(table.rows):
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)
        if row_index == 0 and len(table.rows) > 1:
            table_header = OxmlElement("w:tblHeader")
            table_header.set(qn("w:val"), "true")
            tr_pr.append(table_header)
        for cell, width in zip(row.cells, widths, strict=False):
            _set_cell_width(cell, width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tc_pr = cell._tc.get_or_add_tcPr()
            margins = tc_pr.find(qn("w:tcMar"))
            if margins is None:
                margins = OxmlElement("w:tcMar")
                tc_pr.append(margins)
            for edge, value in (("top", 80), ("bottom", 80), ("start", 120), ("end", 120)):
                node = margins.find(qn(f"w:{edge}"))
                if node is None:
                    node = OxmlElement(f"w:{edge}")
                    margins.append(node)
                node.set(qn("w:w"), str(value))
                node.set(qn("w:type"), "dxa")


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_run(run, size: float = 11, bold: bool = False, color: str = "000000") -> None:
    run.font.name = "Calibri"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def _set_style(style, size: float, color: str, before: float, after: float) -> None:
    style.font.name = "Calibri"
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)


def _add_page_field(paragraph, field_name: str) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = field_name
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, end])
    _set_run(run, size=9, color=MUTED)


def _configure_docx(document: DocumentObject) -> None:
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    normal = document.styles["Normal"]
    _set_style(normal, 11, "000000", 0, 6)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _set_style(document.styles["Heading 1"], 16, BLUE, 16, 8)
    _set_style(document.styles["Heading 2"], 13, BLUE, 12, 6)
    _set_style(document.styles["Heading 3"], 12, DARK_BLUE, 8, 4)

    header = section.header.paragraphs[0]
    header.text = "制造业项目申报预评估｜公开资料演示"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        _set_run(run, size=8.5, color=MUTED)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = footer.add_run("第 ")
    _set_run(run, size=9, color=MUTED)
    _add_page_field(footer, "PAGE")
    run = footer.add_run(" 页 / 共 ")
    _set_run(run, size=9, color=MUTED)
    _add_page_field(footer, "NUMPAGES")
    run = footer.add_run(" 页")
    _set_run(run, size=9, color=MUTED)


def _add_title_block(document: DocumentObject, run: WorkflowRun) -> None:
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(6)
    _set_run(p.add_run(run.company_name), size=12, bold=True, color=MUTED)
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    _set_run(p.add_run("制造业项目申报预评估报告"), size=24, bold=True, color=NAVY)
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(22)
    _set_run(p.add_run("条件匹配、材料检查、引用依据与人工审批轨迹"), size=12, color=MUTED)

    table = document.add_table(rows=3, cols=2)
    values = [
        ("评估日期", run.as_of.isoformat()),
        ("执行编号", run.run_id),
        ("审批状态", run.approval_status),
    ]
    for row, (label, value) in zip(table.rows, values, strict=True):
        row.cells[0].text = label
        row.cells[1].text = value
        _shade(row.cells[0], LIGHT_FILL)
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for text_run in paragraph.runs:
                    _set_run(text_run, bold=cell is row.cells[0])
    _set_table_geometry(table, [2700, 6660])
    document.add_paragraph()

    warning = document.add_table(rows=1, cols=1)
    warning.cell(0, 0).text = (
        "重要说明：本报告由公开政策与虚构企业数据生成，仅用于软件演示，"
        "不构成申报、法律或财务意见；任何对外提交均须人工复核。"
    )
    _shade(warning.cell(0, 0), "FFF8E8")
    for text_run in warning.cell(0, 0).paragraphs[0].runs:
        _set_run(text_run, size=10, color="7A5A00")
    _set_table_geometry(warning, [TABLE_WIDTH_DXA])


def _status_zh(status: RuleStatus) -> str:
    return {
        RuleStatus.PASS: "通过",
        RuleStatus.FAIL: "不通过",
        RuleStatus.UNKNOWN: "待补充",
        RuleStatus.NOT_APPLICABLE: "不适用",
    }[status]


def _add_assessment(document: DocumentObject, assessment: PolicyAssessment) -> None:
    document.add_heading(assessment.policy_title, level=1)
    p = document.add_paragraph()
    _set_run(p.add_run("结论："), bold=True, color=NAVY)
    _set_run(p.add_run(assessment.conclusion))

    document.add_heading("条件核验", level=2)
    table = document.add_table(rows=1, cols=4)
    widths = [2500, 1200, 1900, 3760]
    for cell, label in zip(table.rows[0].cells, ("条件", "结果", "企业值", "政策依据"), strict=True):
        cell.text = label
        _shade(cell, LIGHT_FILL)
        for text_run in cell.paragraphs[0].runs:
            _set_run(text_run, bold=True, color=NAVY)
    for result in assessment.rule_results:
        cells = table.add_row().cells
        citation = "；".join(f"{c.title}（{c.locator}）" for c in result.citations[:2]) or "无"
        values = (result.label, _status_zh(result.status), str(result.actual), citation)
        for cell, value in zip(cells, values, strict=True):
            cell.text = value
            for text_run in cell.paragraphs[0].runs:
                color = RISK if result.status == RuleStatus.FAIL else "000000"
                _set_run(text_run, size=9.5, color=color)
    _set_table_geometry(table, widths)

    source_p = document.add_paragraph()
    source_p.paragraph_format.space_before = Pt(4)
    source_p.paragraph_format.space_after = Pt(4)
    _set_run(source_p.add_run("引用定位以政策原文页码、段落或表格行号为准。"), size=9, color=MUTED)

    document.add_heading("材料检查", level=2)
    table = document.add_table(rows=1, cols=3)
    for cell, label in zip(table.rows[0].cells, ("材料", "状态", "说明"), strict=True):
        cell.text = label
        _shade(cell, LIGHT_FILL)
        for text_run in cell.paragraphs[0].runs:
            _set_run(text_run, bold=True, color=NAVY)
    for material in assessment.material_results:
        cells = table.add_row().cells
        for cell, value in zip(
            cells, (material.label, _status_zh(material.status), material.reason), strict=True
        ):
            cell.text = value
            for text_run in cell.paragraphs[0].runs:
                _set_run(text_run, size=9.5)
    _set_table_geometry(table, [2600, 1200, 5560])

    if assessment.consistency_findings:
        document.add_heading("一致性风险", level=2)
        for finding in assessment.consistency_findings:
            p = document.add_paragraph(style="List Bullet")
            _set_run(
                p.add_run(f"{finding.severity.upper()}：{finding.message}"),
                color=RISK if finding.severity == "error" else "7A5A00",
            )


def export_docx(run: WorkflowRun, path: Path) -> Path:
    document = Document()
    _configure_docx(document)
    _add_title_block(document, run)
    for index, assessment in enumerate(run.assessments):
        if index:
            spacer = document.add_paragraph()
            spacer.paragraph_format.space_after = Pt(8)
        _add_assessment(document, assessment)
    document.add_heading("审批与执行轨迹", level=1)
    for event in run.audit_events:
        p = document.add_paragraph(style="List Number")
        _set_run(
            p.add_run(
                f"{event.timestamp:%Y-%m-%d %H:%M:%S}｜{event.event_type}｜{event.actor}｜"
                f"校验值 {event.event_hash[:12]}"
            ),
            size=9.5,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def _pdf_footer(canvas, doc) -> None:
    canvas.saveState()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(colors.HexColor("#5E6B78"))
    canvas.drawString(0.75 * inch, 0.45 * inch, "制造业项目申报预评估｜公开资料演示")
    canvas.drawRightString(7.75 * inch, 0.45 * inch, f"第 {doc.page} 页")
    canvas.restoreState()


def _p(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_pdf(run: WorkflowRun, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ChineseBody",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    title = ParagraphStyle(
        "ChineseTitle",
        parent=body,
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0B2545"),
        spaceAfter=8,
    )
    subtitle = ParagraphStyle(
        "ChineseSubtitle", parent=body, alignment=TA_CENTER, textColor=colors.HexColor("#5E6B78")
    )
    h1 = ParagraphStyle(
        "ChineseH1", parent=body, fontSize=15, leading=19, textColor=colors.HexColor("#2E74B5"), spaceBefore=14, spaceAfter=8
    )
    h2 = ParagraphStyle(
        "ChineseH2", parent=body, fontSize=12.5, leading=16, textColor=colors.HexColor("#2E74B5"), spaceBefore=10, spaceAfter=6
    )
    small = ParagraphStyle("ChineseSmall", parent=body, fontSize=8.5, leading=11, alignment=TA_LEFT)

    story: list = [
        Spacer(1, 0.35 * inch),
        Paragraph(_p(run.company_name), subtitle),
        Paragraph("制造业项目申报预评估报告", title),
        Paragraph("条件匹配、材料检查、引用依据与人工审批轨迹", subtitle),
        Spacer(1, 0.18 * inch),
    ]
    meta = Table(
        [["评估日期", run.as_of.isoformat()], ["执行编号", run.run_id], ["审批状态", run.approval_status]],
        colWidths=[1.5 * inch, 5 * inch],
        repeatRows=0,
    )
    meta.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F6F9")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D7DE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            meta,
            Spacer(1, 0.18 * inch),
            Paragraph(
                "重要说明：本报告由公开政策与虚构企业数据生成，仅用于软件演示，不构成申报、法律或财务意见；任何对外提交均须人工复核。",
                body,
            ),
        ]
    )
    for index, assessment in enumerate(run.assessments):
        if index:
            story.append(PageBreak())
        story.extend(
            [
                Paragraph(_p(assessment.policy_title), h1),
                Paragraph(f"<b>结论：</b>{_p(assessment.conclusion)}", body),
                Paragraph("条件核验", h2),
            ]
        )
        rule_rows = [[Paragraph(value, small) for value in ("条件", "结果", "企业值", "政策依据")]]
        for result in assessment.rule_results:
            citation = "；".join(f"{c.title}（{c.locator}）" for c in result.citations[:2]) or "无"
            rule_rows.append(
                [
                    Paragraph(_p(result.label), small),
                    Paragraph(_status_zh(result.status), small),
                    Paragraph(_p(result.actual), small),
                    Paragraph(_p(citation), small),
                ]
            )
        table = Table(rule_rows, colWidths=[1.55 * inch, 0.72 * inch, 1.15 * inch, 3.08 * inch], repeatRows=1)
        table.setStyle(_pdf_table_style())
        story.extend([table, Paragraph("引用定位以政策原文页码、段落或表格行号为准。", small), Paragraph("材料检查", h2)])
        material_rows = [[Paragraph(value, small) for value in ("材料", "状态", "说明")]]
        for material in assessment.material_results:
            material_rows.append(
                [
                    Paragraph(_p(material.label), small),
                    Paragraph(_status_zh(material.status), small),
                    Paragraph(_p(material.reason), small),
                ]
            )
        table = Table(material_rows, colWidths=[1.8 * inch, 0.8 * inch, 3.9 * inch], repeatRows=1)
        table.setStyle(_pdf_table_style())
        story.append(table)

    story.append(Paragraph("审批与执行轨迹", h1))
    for event in run.audit_events:
        story.append(
            Paragraph(
                _p(
                    f"{event.sequence}. {event.timestamp:%Y-%m-%d %H:%M:%S}｜{event.event_type}｜"
                    f"{event.actor}｜校验值 {event.event_hash[:12]}"
                ),
                small,
            )
        )
    pdf = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=0.75 * inch,
        title=f"{run.company_name}制造业项目申报预评估报告",
        author="Manufacturing Project Application Agent",
    )
    pdf.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    return path


def _pdf_table_style() -> TableStyle:
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F6F9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0B2545")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D7DE")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def export_all(run: WorkflowRun, directory: Path, formats: Iterable[str]) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for format_name in formats:
        normalized = format_name.lower()
        path = directory / f"{run.run_id}_assessment.{normalized}"
        if normalized == "docx":
            outputs[normalized] = export_docx(run, path)
        elif normalized == "pdf":
            outputs[normalized] = export_pdf(run, path)
        else:
            raise ValueError(f"Unsupported export format: {format_name}")
    return outputs

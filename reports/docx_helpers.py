"""
Вспомогательные функции для сборки отчёта .docx (python-docx):
стили, таблицы из DataFrame, рисунки с подписями, оглавление, номера страниц.
"""
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BODY_FONT = "Times New Roman"
HEAD_FONT = "Arial"
ACCENT = RGBColor(0x18, 0x4F, 0x95)
HEADER_FILL = "CDE2FB"


def _set_font(style_or_run, name: str) -> None:
    """Задаёт шрифт для всех наборов символов (латиница, кириллица, восточные)."""
    style_or_run.font.name = name
    rpr = style_or_run.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)


def new_document() -> Document:
    """Документ A4 с полями 2 см и настроенными стилями."""
    doc = Document()
    section = doc.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21.0)
    section.orientation = WD_ORIENT.PORTRAIT
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(2.0))
    section.left_margin = Cm(2.5)

    normal = doc.styles["Normal"]
    _set_font(normal, BODY_FONT)
    normal.font.size = Pt(12)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for level, size, before in ((1, 16, 18), (2, 13, 12), (3, 12, 10)):
        style = doc.styles[f"Heading {level}"]
        _set_font(style, HEAD_FONT)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = ACCENT
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.keep_with_next = True

    caption = doc.styles["Caption"]
    _set_font(caption, BODY_FONT)
    caption.font.size = Pt(10)
    caption.font.italic = False
    caption.font.bold = False
    caption.font.color.rgb = RGBColor(0x40, 0x40, 0x40)

    for name in ("List Bullet", "List Number"):
        _set_font(doc.styles[name], BODY_FONT)
        doc.styles[name].font.size = Pt(12)
        doc.styles[name].paragraph_format.space_after = Pt(3)
    add_page_numbers(doc)
    return doc


def add_field(paragraph, instruction: str, placeholder: str = "") -> None:
    """Вставляет поле Word (PAGE, TOC и т.п.)."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instr, separate, text, end):
        run._r.append(element)


def add_page_numbers(doc: Document) -> None:
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_field(footer, "PAGE", "1")


def add_toc(doc: Document) -> None:
    # заголовок — обычный абзац, чтобы «Содержание» само не попадало в оглавление
    p = doc.add_paragraph()
    run = p.add_run("Содержание")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(16), ACCENT
    run.font.name = HEAD_FONT
    add_field(doc.add_paragraph(), r'TOC \o "1-2" \h \z \u',
              "Оглавление обновляется при открытии (F9).")


def heading_new_page(doc: Document, text: str, level: int = 1):
    """Заголовок с новой страницы (page_break_before) — не даёт пустых страниц."""
    h = doc.add_heading(text, level=level)
    h.paragraph_format.page_break_before = True
    return h


def page_break(doc: Document) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def para(doc: Document, text: str, bold_prefix: str | None = None, align_justify: bool = True):
    """Абзац текста; bold_prefix — выделенное начало («Цель.»)."""
    p = doc.add_paragraph()
    if bold_prefix:
        p.add_run(bold_prefix + " ").bold = True
    p.add_run(text)
    if align_justify:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


def bullets(doc: Document, items: list[str], numbered: bool = False) -> None:
    """Список. numbered=True — номер «1.» пишется в тексте, чтобы каждый список
    начинался с 1 (автонумерация Word продолжила бы предыдущий список)."""
    for number, item in enumerate(items, start=1):
        p = doc.add_paragraph(style="Normal" if numbered else "List Bullet")
        if numbered:
            p.paragraph_format.left_indent = Cm(0.9)
            p.paragraph_format.first_line_indent = Cm(-0.6)
            p.paragraph_format.space_after = Pt(3)
            p.add_run(f"{number}. ")
        if item.startswith("**") and "**" in item[2:]:
            head, tail = item[2:].split("**", 1)
            p.add_run(head).bold = True
            p.add_run(tail)
        else:
            p.add_run(item)


def caption(doc: Document, text: str):
    p = doc.add_paragraph(text, style="Caption")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    return p


def table_caption(doc: Document, text: str):
    p = doc.add_paragraph(text, style="Caption")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    return p


def figure(doc: Document, path: Path, text: str, width_cm: float = 16.0) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    caption(doc, text)


def _shade(cell, fill: str) -> None:
    tc_pr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def df_table(doc: Document, df: pd.DataFrame, widths_cm: list[float], font_size: float = 9.5,
             align_numbers_right: bool = True) -> None:
    """Таблица из DataFrame: заголовок с заливкой, фиксированные ширины столбцов."""
    table = doc.add_table(rows=1, cols=len(df.columns))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, col in enumerate(df.columns):
        cell = table.rows[0].cells[i]
        cell.width = Cm(widths_cm[i])
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(col))
        run.bold = True
        run.font.size = Pt(font_size)
        _shade(cell, HEADER_FILL)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].width = Cm(widths_cm[i])
            text = "" if (value is None or (isinstance(value, float) and pd.isna(value))) else str(value)
            run = cells[i].paragraphs[0].add_run(text)
            run.font.size = Pt(font_size)
            if align_numbers_right and _is_number(text):
                cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    # небольшие таблицы не разрываем между страницами (строки держатся вместе)
    if len(df) <= 12:
        for row in table.rows[:-1]:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next = True
    # повторять строку заголовка на каждой странице
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _is_number(text: str) -> bool:
    cleaned = (text.replace(" ", "").replace(" ", "").replace(",", ".").replace("%", "")
               .replace("−", "-").replace("×", ""))
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def fmt_int(value) -> str:
    """12345 → '12 345' (неразрывный пробел как разделитель тысяч)."""
    return f"{int(round(value)):,}".replace(",", " ")


def fmt_num(value, digits: int = 1) -> str:
    """12345.67 → '12 345,7' (десятичная запятая, как принято в русском тексте)."""
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")

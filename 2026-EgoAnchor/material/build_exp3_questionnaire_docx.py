"""把实验三双语 Markdown 问卷确定性构建为可打印 DOCX。"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

for prefix, namespace in (
    ("w", W_NS),
    ("r", R_NS),
    ("cp", CP_NS),
    ("dc", DC_NS),
    ("dcterms", DCTERMS_NS),
    ("xsi", XSI_NS),
):
    ET.register_namespace(prefix, namespace)


def _qn(namespace: str, name: str) -> str:
    """返回 ElementTree 使用的限定 XML 名称。"""

    return f"{{{namespace}}}{name}"


def _parse_arguments() -> argparse.Namespace:
    """解析源 Markdown 与目标 DOCX 路径。"""

    material = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=material / "EgoAnchor_Experiment3_Complete_Questionnaire_v5_3_Bilingual.md",
        help="唯一事实源 Markdown 路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=material / "EgoAnchor_Experiment3_Complete_Questionnaire_v5_3_Bilingual.docx",
        help="生成的 DOCX 路径。",
    )
    return parser.parse_args()


def _parse_markdown(text: str) -> list[tuple[str, str]]:
    """把问卷 Markdown 拆成标题、正文、提示、选项和分页块。"""

    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            blocks.append((f"heading{len(heading.group(1))}", heading.group(2).strip()))
            index += 1
            continue
        if line.strip() == "---":
            blocks.append(("page_break", ""))
            index += 1
            continue
        if line.startswith(">"):
            values: list[str] = []
            while index < len(lines) and lines[index].startswith(">"):
                values.append(lines[index].lstrip("> ").rstrip())
                index += 1
            blocks.append(("quote", "\n".join(values)))
            continue
        if line.startswith("- [ ]"):
            blocks.append(("checkbox", line.replace("- [ ]", "□").strip()))
            index += 1
            continue
        if line.startswith("- "):
            values = [line[2:].rstrip()]
            index += 1
            while index < len(lines) and lines[index].startswith("  "):
                values.append(lines[index].strip())
                index += 1
            blocks.append(("bullet", "\n".join(values)))
            continue
        values = []
        while index < len(lines):
            current = lines[index]
            if not current.strip() or re.match(r"^(#{1,3})\s+", current):
                break
            if current.strip() == "---" or current.startswith(">") or current.startswith("- "):
                break
            hard_break = current.endswith("  ")
            values.append(current.rstrip())
            index += 1
            if hard_break:
                values.append("\n")
        paragraph = " ".join(values).replace(" \n ", "\n").replace("\n ", "\n")
        blocks.append(("body", paragraph.strip()))
    return blocks


def _append_inline_runs(paragraph: ET.Element, text: str) -> None:
    """把粗体、斜体、代码和显式换行写成 Word runs。"""

    token_pattern = re.compile(r"(\*\*.*?\*\*|(?<!\*)\*[^*]+?\*(?!\*)|`[^`]+`)")
    for line_index, line in enumerate(text.split("\n")):
        if line_index:
            run = ET.SubElement(paragraph, _qn(W_NS, "r"))
            ET.SubElement(run, _qn(W_NS, "br"))
        cursor = 0
        for token in token_pattern.finditer(line):
            if token.start() > cursor:
                _append_run(paragraph, line[cursor : token.start()])
            value = token.group(0)
            if value.startswith("**"):
                _append_run(paragraph, value[2:-2], bold=True)
            elif value.startswith("*"):
                _append_run(paragraph, value[1:-1], italic=True)
            else:
                _append_run(paragraph, value[1:-1], code=True)
            cursor = token.end()
        if cursor < len(line):
            _append_run(paragraph, line[cursor:])


def _append_run(
    paragraph: ET.Element,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
) -> None:
    """向一个段落写入带基础字符格式的文本 run。"""

    if not text:
        return
    run = ET.SubElement(paragraph, _qn(W_NS, "r"))
    properties = ET.SubElement(run, _qn(W_NS, "rPr"))
    if bold:
        ET.SubElement(properties, _qn(W_NS, "b"))
    if italic:
        ET.SubElement(properties, _qn(W_NS, "i"))
    if code:
        fonts = ET.SubElement(properties, _qn(W_NS, "rFonts"))
        fonts.set(_qn(W_NS, "ascii"), "Consolas")
        fonts.set(_qn(W_NS, "hAnsi"), "Consolas")
    node = ET.SubElement(run, _qn(W_NS, "t"))
    if text[:1].isspace() or text[-1:].isspace():
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text


def _paragraph(
    body: ET.Element,
    style: str,
    text: str,
    *,
    keep_next: bool = False,
    bullet: bool = False,
) -> ET.Element:
    """创建一个带稳定样式、分页和编号属性的正文段落。"""

    paragraph = ET.SubElement(body, _qn(W_NS, "p"))
    properties = ET.SubElement(paragraph, _qn(W_NS, "pPr"))
    style_node = ET.SubElement(properties, _qn(W_NS, "pStyle"))
    style_node.set(_qn(W_NS, "val"), style)
    if keep_next:
        ET.SubElement(properties, _qn(W_NS, "keepNext"))
    if bullet:
        numbering = ET.SubElement(properties, _qn(W_NS, "numPr"))
        level = ET.SubElement(numbering, _qn(W_NS, "ilvl"))
        level.set(_qn(W_NS, "val"), "0")
        number = ET.SubElement(numbering, _qn(W_NS, "numId"))
        number.set(_qn(W_NS, "val"), "1")
    _append_inline_runs(paragraph, text)
    return paragraph


def _page_break(body: ET.Element) -> None:
    """插入明确分页，保持每个区块和方法问卷独立打印。"""

    paragraph = ET.SubElement(body, _qn(W_NS, "p"))
    run = ET.SubElement(paragraph, _qn(W_NS, "r"))
    node = ET.SubElement(run, _qn(W_NS, "br"))
    node.set(_qn(W_NS, "type"), "page")


def _document_xml(blocks: list[tuple[str, str]]) -> bytes:
    """根据解析后的 Markdown 块生成主文档 XML。"""

    document = ET.Element(_qn(W_NS, "document"))
    body = ET.SubElement(document, _qn(W_NS, "body"))
    question_tail = 0
    first_heading = True
    for kind, text in blocks:
        if kind == "page_break":
            _page_break(body)
            question_tail = 0
            continue
        if kind == "heading1":
            style = "Title" if first_heading else "Heading1"
            _paragraph(body, style, text, keep_next=True)
            first_heading = False
            question_tail = 0
            continue
        if kind == "heading2":
            _paragraph(body, "Heading2", text, keep_next=True)
            question_tail = 0
            continue
        if kind == "heading3":
            _paragraph(body, "Heading3", text, keep_next=True)
            question_tail = 2
            continue
        if kind == "quote":
            _paragraph(body, "Quote", text)
            question_tail = 0
            continue
        if kind == "checkbox":
            _paragraph(body, "Checkbox", text)
            question_tail = 0
            continue
        if kind == "bullet":
            _paragraph(body, "Bullet", text, bullet=True)
            question_tail = 0
            continue
        _paragraph(body, "Normal", text, keep_next=question_tail > 0)
        question_tail = max(0, question_tail - 1)

    section = ET.SubElement(body, _qn(W_NS, "sectPr"))
    footer = ET.SubElement(section, _qn(W_NS, "footerReference"))
    footer.set(_qn(W_NS, "type"), "default")
    footer.set(_qn(R_NS, "id"), "rId1")
    page_size = ET.SubElement(section, _qn(W_NS, "pgSz"))
    page_size.set(_qn(W_NS, "w"), "11906")
    page_size.set(_qn(W_NS, "h"), "16838")
    margins = ET.SubElement(section, _qn(W_NS, "pgMar"))
    for key, value in {
        "top": "1134",
        "right": "1134",
        "bottom": "1134",
        "left": "1134",
        "header": "567",
        "footer": "567",
        "gutter": "0",
    }.items():
        margins.set(_qn(W_NS, key), value)
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)


def _styles_xml() -> bytes:
    """生成适合双语纸质问卷的紧凑 Word 样式表。"""

    styles = ET.Element(_qn(W_NS, "styles"))
    defaults = ET.SubElement(styles, _qn(W_NS, "docDefaults"))
    run_defaults = ET.SubElement(ET.SubElement(defaults, _qn(W_NS, "rPrDefault")), _qn(W_NS, "rPr"))
    fonts = ET.SubElement(run_defaults, _qn(W_NS, "rFonts"))
    for key, value in {
        "ascii": "Arial",
        "hAnsi": "Arial",
        "eastAsia": "Microsoft YaHei",
        "cs": "Arial",
    }.items():
        fonts.set(_qn(W_NS, key), value)
    size = ET.SubElement(run_defaults, _qn(W_NS, "sz"))
    size.set(_qn(W_NS, "val"), "20")
    size_cs = ET.SubElement(run_defaults, _qn(W_NS, "szCs"))
    size_cs.set(_qn(W_NS, "val"), "20")
    paragraph_defaults = ET.SubElement(
        ET.SubElement(defaults, _qn(W_NS, "pPrDefault")), _qn(W_NS, "pPr")
    )
    spacing = ET.SubElement(paragraph_defaults, _qn(W_NS, "spacing"))
    spacing.set(_qn(W_NS, "after"), "80")
    spacing.set(_qn(W_NS, "line"), "276")
    spacing.set(_qn(W_NS, "lineRule"), "auto")

    _style(styles, "Normal", "Normal", 20, 80)
    _style(styles, "Title", "标题", 34, 160, bold=True, color="17365D", align="center")
    _style(styles, "Heading1", "一级标题", 28, 140, bold=True, color="17365D", outline=0)
    _style(styles, "Heading2", "二级标题", 24, 110, bold=True, color="1F4E79", outline=1)
    _style(styles, "Heading3", "题目标题", 21, 70, bold=True, color="2F5597", outline=2)
    _style(styles, "Quote", "提示", 19, 100, color="404040", left=280, shade="EAF2F8")
    _style(styles, "Checkbox", "作答选项", 19, 120, align="center")
    _style(styles, "Bullet", "项目符号", 19, 70, left=360, hanging=180)
    return ET.tostring(styles, encoding="utf-8", xml_declaration=True)


def _style(
    styles: ET.Element,
    style_id: str,
    name: str,
    font_size: int,
    after: int,
    *,
    bold: bool = False,
    color: str | None = None,
    align: str | None = None,
    outline: int | None = None,
    left: int | None = None,
    hanging: int | None = None,
    shade: str | None = None,
) -> None:
    """向样式表加入一个段落样式。"""

    style = ET.SubElement(styles, _qn(W_NS, "style"))
    style.set(_qn(W_NS, "type"), "paragraph")
    style.set(_qn(W_NS, "styleId"), style_id)
    style_name = ET.SubElement(style, _qn(W_NS, "name"))
    style_name.set(_qn(W_NS, "val"), name)
    paragraph_properties = ET.SubElement(style, _qn(W_NS, "pPr"))
    spacing = ET.SubElement(paragraph_properties, _qn(W_NS, "spacing"))
    spacing.set(_qn(W_NS, "after"), str(after))
    if align:
        alignment = ET.SubElement(paragraph_properties, _qn(W_NS, "jc"))
        alignment.set(_qn(W_NS, "val"), align)
    if outline is not None:
        outline_node = ET.SubElement(paragraph_properties, _qn(W_NS, "outlineLvl"))
        outline_node.set(_qn(W_NS, "val"), str(outline))
    if left is not None:
        indent = ET.SubElement(paragraph_properties, _qn(W_NS, "ind"))
        indent.set(_qn(W_NS, "left"), str(left))
        if hanging is not None:
            indent.set(_qn(W_NS, "hanging"), str(hanging))
    if shade:
        shading = ET.SubElement(paragraph_properties, _qn(W_NS, "shd"))
        shading.set(_qn(W_NS, "fill"), shade)
    run_properties = ET.SubElement(style, _qn(W_NS, "rPr"))
    if bold:
        ET.SubElement(run_properties, _qn(W_NS, "b"))
    if color:
        color_node = ET.SubElement(run_properties, _qn(W_NS, "color"))
        color_node.set(_qn(W_NS, "val"), color)
    size = ET.SubElement(run_properties, _qn(W_NS, "sz"))
    size.set(_qn(W_NS, "val"), str(font_size))
    size_cs = ET.SubElement(run_properties, _qn(W_NS, "szCs"))
    size_cs.set(_qn(W_NS, "val"), str(font_size))


def _numbering_xml() -> bytes:
    """生成研究者附录所需的真实项目符号编号。"""

    numbering = ET.Element(_qn(W_NS, "numbering"))
    abstract = ET.SubElement(numbering, _qn(W_NS, "abstractNum"))
    abstract.set(_qn(W_NS, "abstractNumId"), "0")
    level = ET.SubElement(abstract, _qn(W_NS, "lvl"))
    level.set(_qn(W_NS, "ilvl"), "0")
    start = ET.SubElement(level, _qn(W_NS, "start"))
    start.set(_qn(W_NS, "val"), "1")
    fmt = ET.SubElement(level, _qn(W_NS, "numFmt"))
    fmt.set(_qn(W_NS, "val"), "bullet")
    text = ET.SubElement(level, _qn(W_NS, "lvlText"))
    text.set(_qn(W_NS, "val"), "•")
    num = ET.SubElement(numbering, _qn(W_NS, "num"))
    num.set(_qn(W_NS, "numId"), "1")
    abstract_id = ET.SubElement(num, _qn(W_NS, "abstractNumId"))
    abstract_id.set(_qn(W_NS, "val"), "0")
    return ET.tostring(numbering, encoding="utf-8", xml_declaration=True)


def _footer_xml() -> bytes:
    """生成居中的页码页脚。"""

    footer = ET.Element(_qn(W_NS, "ftr"))
    paragraph = ET.SubElement(footer, _qn(W_NS, "p"))
    properties = ET.SubElement(paragraph, _qn(W_NS, "pPr"))
    alignment = ET.SubElement(properties, _qn(W_NS, "jc"))
    alignment.set(_qn(W_NS, "val"), "center")
    field = ET.SubElement(paragraph, _qn(W_NS, "fldSimple"))
    field.set(_qn(W_NS, "instr"), "PAGE")
    run = ET.SubElement(field, _qn(W_NS, "r"))
    text = ET.SubElement(run, _qn(W_NS, "t"))
    text.text = "1"
    return ET.tostring(footer, encoding="utf-8", xml_declaration=True)


def _core_xml(source: Path, digest: str) -> bytes:
    """生成不含个人信息且可追溯源文件摘要的核心属性。"""

    properties = ET.Element(_qn(CP_NS, "coreProperties"))
    ET.SubElement(properties, _qn(DC_NS, "title")).text = "EgoAnchor 实验三完整用户问卷包 v5.3"
    ET.SubElement(properties, _qn(DC_NS, "creator")).text = "EgoAnchor"
    ET.SubElement(properties, _qn(CP_NS, "keywords")).text = f"source={source.name}; sha256={digest}"
    ET.SubElement(properties, _qn(DC_NS, "description")).text = (
        "由 build_exp3_questionnaire_docx.py 从 Markdown 确定性生成。"
    )
    for name in ("created", "modified"):
        node = ET.SubElement(properties, _qn(DCTERMS_NS, name))
        node.set(_qn(XSI_NS, "type"), "dcterms:W3CDTF")
        node.text = "2026-08-03T00:00:00Z"
    return ET.tostring(properties, encoding="utf-8", xml_declaration=True)


def _static_parts() -> dict[str, bytes]:
    """返回 DOCX 包中稳定且与正文无关的 XML 部件。"""

    return {
        "[Content_Types].xml": b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>''',
        "_rels/.rels": b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>''',
        "word/_rels/document.xml.rels": b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>''',
        "word/settings.xml": b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:updateFields w:val="true"/></w:settings>''',
        "docProps/app.xml": b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>EgoAnchor deterministic builder</Application></Properties>''',
    }


def _write_docx(parts: dict[str, bytes], output: Path) -> None:
    """按稳定顺序和固定时间戳写出可复现的 DOCX ZIP 包。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(parts):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, parts[name])
    temporary.replace(output)


def build(source: Path, output: Path) -> Path:
    """读取 Markdown、构建 DOCX，并返回规范化输出路径。"""

    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output == source:
        raise ValueError("DOCX 输出不得覆盖 Markdown 源文件")
    payload = source.read_bytes()
    text = payload.decode("utf-8")
    blocks = _parse_markdown(text)
    parts = _static_parts()
    parts.update(
        {
            "docProps/core.xml": _core_xml(source, hashlib.sha256(payload).hexdigest()),
            "word/document.xml": _document_xml(blocks),
            "word/footer1.xml": _footer_xml(),
            "word/numbering.xml": _numbering_xml(),
            "word/styles.xml": _styles_xml(),
        }
    )
    _write_docx(parts, output)
    return output


def main() -> None:
    """执行命令行构建并输出生成路径。"""

    arguments = _parse_arguments()
    print(build(arguments.source, arguments.output))


if __name__ == "__main__":
    main()

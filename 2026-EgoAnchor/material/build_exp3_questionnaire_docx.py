# -*- coding: utf-8 -*-
"""实验三双语问卷包：由 Markdown 蓝本生成可打印 docx（零依赖，直接写 OOXML）。

唯一事实源是同目录的 `EgoAnchor_Experiment3_Complete_Questionnaire_v5_1_Bilingual.md`；
修改问卷一律先改 md，再重跑本脚本覆盖生成同名 docx，保证两版逐字一致。

转换规则（只支持该 md 实际用到的语法子集）：
- `#`/`##`/`###` -> 三级标题（加粗，16/14/12 pt）；每个 `#` 级标题以及以
  "区块"/"方法级问卷" 开头的 `##` 级标题前插入分页符，便于逐页施测。
- `> ` 引用块 -> 斜体说明段。
- 行内 `**粗体**` 与 `*斜体*` -> 对应字体样式。
- `- [ ]` -> 打印用空心复选框 "☐"；普通 `- ` 列表 -> "• "。
- `---` 分隔线与空行 -> 空段落；其余行按普通段落输出。
- 不写 docProps，固定压缩参数，输出字节确定。
"""

import re  # 行内粗斜体切分用
import zipfile  # docx 打包
from pathlib import Path  # 路径定位

MD_PATH = Path(__file__).parent / "EgoAnchor_Experiment3_Complete_Questionnaire_v5_1_Bilingual.md"  # 输入 md
DOCX_PATH = Path(__file__).parent / "EgoAnchor_Experiment3_Complete_Questionnaire_v5_1_Bilingual.docx"  # 输出 docx


def esc(t: str) -> str:
    """XML 转义。"""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def runs(text: str, base_italic: bool = False) -> str:
    """把一行文本切分为带 **粗体** / *斜体* 的 OOXML run 序列。"""
    out = []
    for tok in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
        if not tok:
            continue
        bold, italic = False, base_italic
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            bold, tok = True, tok[2:-2]
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            italic, tok = True, tok[1:-1]
        props = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + "</w:rPr>"
        out.append(f'<w:r>{props}<w:t xml:space="preserve">{esc(tok)}</w:t></w:r>')
    return "".join(out)


def para(text: str, *, size: int = 0, bold: bool = False, italic: bool = False,
         page_break: bool = False, space_after: int = 120) -> str:
    """生成一个段落；size 为半点字号（0 表示默认），page_break 在段前分页。"""
    rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") \
        + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "") + "</w:rPr>"
    ppr = f'<w:pPr>{"<w:pageBreakBefore/>" if page_break else ""}<w:spacing w:after="{space_after}"/>{rpr}</w:pPr>'
    if bold or italic or size:  # 标题/引用整段统一样式：单一 run 承载全部文本
        style = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") \
            + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "")
        body = f'<w:r><w:rPr>{style}</w:rPr><w:t xml:space="preserve">{esc(text)}</w:t></w:r>'
    else:
        body = runs(text, base_italic=italic)
    return f"<w:p>{ppr}{body}</w:p>"


def convert(md: str) -> str:
    """md 全文 -> document.xml 的 <w:body> 内容。"""
    paras = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line or line.strip() == "---":
            paras.append(para("", space_after=60))
            continue
        if line.startswith("### "):
            paras.append(para(line[4:], size=24, bold=True))
        elif line.startswith("## "):
            text = line[3:]
            pb = text.startswith("区块") or text.startswith("方法级问卷")  # 每区块/每份方法级问卷单独起页
            paras.append(para(text, size=28, bold=True, page_break=pb))
        elif line.startswith("# "):
            paras.append(para(line[2:], size=32, bold=True, page_break=bool(paras)))
        elif line.startswith("> "):
            paras.append(para(line[2:].replace("**", ""), italic=True))
        else:
            text = line.replace("- [ ]", "☐").replace("- [x]", "☑")
            if text.startswith("- "):
                text = "• " + text[2:]
            paras.append(f'<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>{runs(text)}</w:p>')
    return "".join(paras)


DOCUMENT_TMPL = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>{body}"
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
    "</w:body></w:document>"
)

STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="DengXian"/>'
    '<w:sz w:val="21"/><w:szCs w:val="21"/>'
    "</w:rPr></w:rPrDefault></w:docDefaults></w:styles>"
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)

DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)


def main():
    md = MD_PATH.read_text(encoding="utf-8")
    document = DOCUMENT_TMPL.format(body=convert(md))
    with zipfile.ZipFile(DOCX_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [("[Content_Types].xml", CONTENT_TYPES), ("_rels/.rels", ROOT_RELS),
                           ("word/document.xml", document), ("word/_rels/document.xml.rels", DOC_RELS),
                           ("word/styles.xml", STYLES)]:
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 26, 0, 0, 0))  # 固定时间戳保证字节稳定
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    print(f"已从 {MD_PATH.name} 生成 {DOCX_PATH.name}（{DOCX_PATH.stat().st_size} 字节）")


if __name__ == "__main__":
    main()

# ruff: noqa: E501

from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

MAX_XLSX_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_DISEASE_NAMES = 25
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def parse_disease_names_xlsx(payload: bytes) -> tuple[str, ...]:
    if not payload or len(payload) > MAX_XLSX_BYTES:
        raise ValueError("File XLSX phải có dung lượng từ 1 byte đến 2 MB")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Nội dung giải nén XLSX vượt quá 10 MB")
            if any(
                info.filename.startswith(("/", "\\"))
                or ".." in info.filename.split("/")
                for info in infos
            ):
                raise ValueError("XLSX chứa đường dẫn không an toàn")
            shared = _shared_strings(archive)
            try:
                sheet = archive.read("xl/worksheets/sheet1.xml")
            except KeyError as exc:
                raise ValueError("XLSX không có worksheet đầu tiên") from exc
    except BadZipFile as exc:
        raise ValueError("File không phải định dạng XLSX hợp lệ") from exc

    try:
        root = ElementTree.fromstring(sheet)
    except ElementTree.ParseError as exc:
        raise ValueError("Worksheet XLSX không hợp lệ") from exc

    names: list[str] = []
    seen: set[str] = set()
    for cell in root.findall(f".//{{{SPREADSHEET_NS}}}c"):
        reference = cell.get("r", "")
        if not reference.startswith("A"):
            continue
        value = _cell_text(cell, shared)
        name = " ".join(value.split())
        identity = name.casefold()
        if not name or identity in {"disease", "name", "disease name", "tên bệnh"}:
            continue
        if identity in seen:
            continue
        seen.add(identity)
        names.append(name)
        if len(names) > MAX_DISEASE_NAMES:
            raise ValueError("File XLSX hỗ trợ tối đa 25 tên bệnh")
    if not names:
        raise ValueError("Không tìm thấy tên bệnh trong cột A của XLSX")
    return tuple(names)


def build_disease_import_template() -> bytes:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Disease Import" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        "xl/styles.xml": """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font/><font><b/><color rgb="FFFFFFFF"/></font></fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF087F78"/><bgColor indexed="64"/></patternFill></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="2"><xf/><xf fontId="1" fillId="1" applyFont="1" applyFill="1"/></cellXfs>
</styleSheet>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols><col min="1" max="1" width="32" customWidth="1"/><col min="2" max="2" width="52" customWidth="1"/></cols>
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr" s="1"><is><t>Disease Name</t></is></c>
      <c r="B1" t="inlineStr" s="1"><is><t>Instructions</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>Down syndrome</t></is></c>
      <c r="B2" t="inlineStr"><is><t>Replace examples; one disease per row in column A.</t></is></c>
    </row>
    <row r="3"><c r="A3" t="inlineStr"><is><t>Sepsis</t></is></c></row>
  </sheetData>
</worksheet>""",
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return ()
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError("Shared strings XLSX không hợp lệ") from exc
    return tuple(
        "".join(
            node.text or ""
            for node in item.findall(f".//{{{SPREADSHEET_NS}}}t")
        )
        for item in root.findall(f"{{{SPREADSHEET_NS}}}si")
    )


def _cell_text(
    cell: ElementTree.Element,
    shared: tuple[str, ...],
) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or ""
            for node in cell.findall(f".//{{{SPREADSHEET_NS}}}t")
        )
    value = cell.findtext(f"{{{SPREADSHEET_NS}}}v", default="")
    if cell_type == "s" and value.isdigit():
        index = int(value)
        return shared[index] if index < len(shared) else ""
    return value

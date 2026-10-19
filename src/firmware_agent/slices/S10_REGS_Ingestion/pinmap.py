"""Pin-map ingestion - read the hardware IO mapping table, answer questions about it,
and never pretend a question was answered when nothing was found.

Why a dedicated reader instead of handing the spreadsheet to a model: the pin table is
the one hardware input that is *tabular*, so "which pin carries this net" is a lookup
with an answer that can be checked. A model asked the same question can produce a
plausible pin that exists in the MCU but not on this board, and nothing downstream can
tell. Lookups fail loudly; plausible pins do not.

The discipline that matters most here is the empty result. "No rows" has two completely
different meanings - the table says no, and the table cannot say - and collapsing them
is how an assembled prompt ends up silently missing a peripheral. Every query therefore
carries where it looked, and a skipped sheet is reported rather than ignored.

xlsx is read with the standard library only. Customer IO maps arrive as xlsx; making
that need a dependency would put a parse failure in front of the first hardware
question anyone asks.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

__all__ = ["PinMap", "PinQuery", "PinRow"]

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_MAIN = _NS["m"]

# Located by header text, never by column index: hardware teams insert columns, and a
# positional reader would silently read "Pin type" as if it were the net name.
_REQUIRED_HEADERS = {"pin number": "pin", "netlist": "net"}
_OPTIONAL_HEADERS = {
    "pin name (default)": "name",
    "pin name": "name",
    "pin type": "pin_type",
    "function description": "function",
    "function": "function",
    "remark": "remark",
    "description": "function",
}


def _column_index(reference: str) -> int:
    """`C7` -> 2. Cells are sparse in xlsx, so position comes from the reference."""
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return -1
    index = 0
    for char in letters.group(0):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN}}}t"))
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        index = int(value.text)
        return shared[index] if index < len(shared) else ""
    return value.text


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    # One <si> may be split into several <r><t> runs; the string is their concatenation.
    return ["".join(node.text or "" for node in si.iter(f"{{{_MAIN}}}t"))
            for si in root.findall("m:si", _NS)]


def _sheet_files(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(sheet name, zip member), in workbook order, resolved through the relationships."""
    if "xl/workbook.xml" not in archive.namelist():
        return []
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    try:
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return []
    target_for = {
        rel.get("Id"): rel.get("Target")
        for rel in relationships
        if rel.get("Id") and rel.get("Target")
    }
    sheets = []
    for sheet in workbook.iter(f"{{{_MAIN}}}sheet"):
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = target_for.get(rid)
        if not target:
            continue
        path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        if path in archive.namelist():
            sheets.append((sheet.get("name") or "?", path))
    return sheets


def _rows(archive: zipfile.ZipFile, member: str, shared: list[str]) -> list[list[str]]:
    sheet = ET.fromstring(archive.read(member))
    table = []
    for row in sheet.iter(f"{{{_MAIN}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall("m:c", _NS):
            index = _column_index(cell.get("r") or "")
            if index >= 0:
                cells[index] = _cell_text(cell, shared)
        width = max(cells) + 1 if cells else 0
        table.append([cells.get(i, "") for i in range(width)])
    return table


def _normalise(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class PinRow:
    """One pin, with the coordinates it was read from.

    The coordinates are not decoration: once a prompt fragment comes from a row, "which
    line of which hardware document" has to be answerable, and net names are quoted as
    written (including stray spaces) so the row can be found again by eye.
    """

    device: str
    pin: str
    net: str
    name: str = ""
    pin_type: str = ""
    function: str = ""
    remark: str = ""
    doc: str = ""
    sheet: str = ""
    row_number: int = 0

    def citation(self) -> str:
        return f"{Path(self.doc).name}[{self.sheet}]!row {self.row_number}"

    def as_prompt_fragment(self) -> str:
        parts = [f"Pin {self.pin}", f"net {_normalise(self.net) or '-'}"]
        for label, value in (("default name", self.name), ("type", self.pin_type),
                             ("function", self.function), ("remark", self.remark)):
            if _normalise(value):
                parts.append(f"{label}: {_normalise(value)}")
        return ", ".join(parts)


@dataclass(frozen=True)
class PinQuery:
    """A lookup and the record of where it looked. An empty result explains itself."""

    term: str
    rows: tuple[PinRow, ...]
    searched_rows: int
    searched_devices: tuple[str, ...]
    skipped_sheets: tuple[tuple[str, str], ...] = ()
    doc: str = ""

    @property
    def found(self) -> bool:
        return bool(self.rows)

    @property
    def nets(self) -> list[str]:
        return [_normalise(row.net) for row in self.rows]

    def why_empty(self) -> str:
        scope = f"{self.searched_rows} 行，来自 {len(self.searched_devices)} 张器件表"
        if self.searched_devices:
            scope += f"（{', '.join(self.searched_devices)}）"
        note = f"在 {Path(self.doc).name} 的 {scope} 中找不到 {self.term!r}"
        if self.skipped_sheets:
            skipped = "; ".join(f"{name}（{reason}）" for name, reason in self.skipped_sheets)
            note += f"。另有未读入的表：{skipped}"
        return note + "。这是查询无结果，不是硬件确认不存在"


@dataclass(frozen=True)
class PinMap:
    doc: str
    doc_sha256: str
    rows: tuple[PinRow, ...] = ()
    skipped_sheets: tuple[tuple[str, str], ...] = ()
    devices: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> PinMap:
        path = Path(path)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        archive = zipfile.ZipFile(path)
        shared = _shared_strings(archive)
        rows: list[PinRow] = []
        skipped: list[tuple[str, str]] = []
        problems: list[str] = []

        for name, member in _sheet_files(archive):
            table = _rows(archive, member, shared)
            header_index, columns = _find_header(table)
            if header_index is None:
                skipped.append((name, "表头没有 Pin number / Netlist 列，不是引脚表"))
                continue
            for offset, cells in enumerate(table[header_index + 1:], start=header_index + 2):
                pin = _normalise(_at(cells, columns.get("pin", -1)))
                net = _at(cells, columns.get("net", -1))
                if not pin:
                    continue
                rows.append(PinRow(
                    device=name, pin=pin, net=net,
                    name=_normalise(_at(cells, columns.get("name", -1))),
                    pin_type=_normalise(_at(cells, columns.get("pin_type", -1))),
                    function=_normalise(_at(cells, columns.get("function", -1))),
                    remark=_normalise(_at(cells, columns.get("remark", -1))),
                    doc=str(path), sheet=name, row_number=offset,
                ))
            if not any(row.device == name for row in rows):
                problems.append(f"{name}: 表头识别成功但没有一行有效数据")

        return cls(doc=str(path), doc_sha256=digest, rows=tuple(rows),
                   skipped_sheets=tuple(skipped),
                   devices=tuple(dict.fromkeys(row.device for row in rows)),
                   problems=tuple(problems))

    def find(self, term: str) -> PinQuery:
        """Case-insensitive substring over net / pin / default name / function / remark.

        Matching on the function text as well is deliberate: hardware teams write
        "Screen SPI" in a description and leave the net name cryptic.
        """
        needle = term.strip().upper()
        # Joined with separators so a term cannot match across a column boundary.
        matches = tuple(row for row in self.rows
                        if needle in f"{row.net} | {row.pin} | {row.name} | {row.function} | {row.remark}".upper())
        return PinQuery(term=term, rows=matches,
                        searched_rows=len(self.rows),
                        searched_devices=self.devices,
                        skipped_sheets=self.skipped_sheets, doc=self.doc)

    def by_pin(self, pin: str) -> PinQuery:
        """Exact match on either identifier for a pin.

        The table carries two names for the same piece of silicon - the package ball
        (`E3`) and the default port name (`P7.3`) - and people ask for both. Matching
        only the first made every human question come back empty, which is the worst
        possible failure: the data was there.
        """
        want = _normalise(pin).upper()
        matches = tuple(row for row in self.rows if want in (row.pin.upper(), row.name.upper()))
        return PinQuery(term=pin, rows=matches, searched_rows=len(self.rows),
                        searched_devices=self.devices, skipped_sheets=self.skipped_sheets, doc=self.doc)

    def of_type(self, pin_type: str) -> PinQuery:
        want = pin_type.strip().upper()
        matches = tuple(row for row in self.rows if row.pin_type.upper() == want)
        return PinQuery(term=f"type={pin_type}", rows=matches, searched_rows=len(self.rows),
                        searched_devices=self.devices, skipped_sheets=self.skipped_sheets, doc=self.doc)


def _at(cells: list[str], index: int) -> str:
    if index < 0 or index >= len(cells):
        return ""
    return cells[index]


def _find_header(table: list[list[str]]) -> tuple[int | None, dict[str, int]]:
    """Find the header row by content, within the first few rows."""
    for index, cells in enumerate(table[:8]):
        columns: dict[str, int] = {}
        for position, cell in enumerate(cells):
            key = _normalise(cell).lower()
            if key in _REQUIRED_HEADERS:
                columns[_REQUIRED_HEADERS[key]] = position
            elif key in _OPTIONAL_HEADERS:
                columns.setdefault(_OPTIONAL_HEADERS[key], position)
        if "pin" in columns and "net" in columns:
            return index, columns
    return None, {}

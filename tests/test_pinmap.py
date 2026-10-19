"""Pin-map reading. The tests below are mostly about the empty answer, because that is
where a hardware lookup does its damage: a wrong pin is a bug someone hits, a silent
"not found" is a peripheral that quietly never appears in the prompt."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from firmware_agent.slices.S10_REGS_Ingestion.pinmap import PinMap

REAL_MAP = Path("demo-project/Docs/hardware/schematic/Adonis-1P 1.5_IO-Mapping_V2.1_20251210.xlsx")

PIN_HEADER = ["Item", "Pin number", "Pin name (Default)", "Pin type", "Netlist", "Function description", "Remark"]


def write_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """Minimal xlsx. Cells are written as inline strings; empty cells are omitted, as a
    real spreadsheet does - which is why column position must come from the cell name."""
    book = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheets, start=1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="t" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("xl/workbook.xml",
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         f"{book}</workbook>")
        archive.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{rels}</Relationships>")
        for i, rows in enumerate(sheets.values(), start=1):
            body = []
            for r, row in enumerate(rows, start=1):
                cells = "".join(
                    f'<c r="{chr(65 + c)}{r}" t="inlineStr"><is><t>{value}</t></is></c>'
                    for c, value in enumerate(row) if value != ""
                )
                body.append(f"<row r=\"{r}\">{cells}</row>")
            archive.writestr(f"xl/worksheets/sheet{i}.xml",
                             f'<sheetData xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                             f"{''.join(body)}</sheetData>")
    return path


def pins(rows: list[list[str]], title: str = "MCU-X") -> list[list[str]]:
    return [[title], PIN_HEADER, *rows]


@pytest.fixture()
def sample(tmp_path: Path) -> PinMap:
    path = write_xlsx(tmp_path / "io.xlsx", {
        "MCU-X": pins([
            ["1", "C11", "VDDD", "Power", "VDDD", "Main digital supply", ""],
            ["2", "E3", "P7.3", "SPI", "LCD_CS", "Screen SPI", "active low"],
            ["3", "F6", "P7.0", "SPI", "LCD_MOSI", "Screen SPI", ""],
        ]),
        "Summary of GPIO": [["Item", "Function", "Quantity"], ["1", "I2C", "1"]],
    })
    return PinMap.load(path)


def test_reads_rows_and_cites_where_each_one_came_from(sample: PinMap) -> None:
    row = sample.find("LCD_CS").rows[0]

    assert (row.pin, row.name, row.net) == ("E3", "P7.3", "LCD_CS")
    assert row.citation() == "io.xlsx[MCU-X]!row 4"


def test_a_pin_is_found_by_either_of_its_two_names(sample: PinMap) -> None:
    """The ball (`E3`) and the port name (`P7.3`) are the same piece of silicon."""
    assert sample.by_pin("E3").found and sample.by_pin("P7.3").found
    assert sample.by_pin("E3").rows == sample.by_pin("P7.3").rows


def test_columns_are_found_by_header_text_not_position(tmp_path: Path) -> None:
    """Hardware teams insert columns. A positional reader would read the pin type as a
    net name and never notice."""
    shuffled = [["Pin type", "Netlist", "Item", "Pin number", "Pin name (Default)", "Remark"],
                ["SPI", "IMU_CS", "9", "B2", "P1.0", "moved"]]
    path = write_xlsx(tmp_path / "shuffled.xlsx", {"MCU-X": [["MCU-X"], *shuffled]})

    row = PinMap.load(path).find("IMU_CS").rows[0]

    assert (row.pin, row.name, row.pin_type) == ("B2", "P1.0", "SPI")


def test_omitted_cells_do_not_shift_the_rest_of_the_row(tmp_path: Path):
    """xlsx stores only non-empty cells, so `Netlist` in column E must still be E."""
    path = write_xlsx(tmp_path / "sparse.xlsx", {"MCU-X": [["MCU-X"], PIN_HEADER,
                                                           ["1", "A1", "P0.1", "", "", "no remark"]]},)
    # The row above leaves columns D and E empty and has no sixth value at all.
    row = PinMap.load(path).by_pin("A1").rows[0]
    assert row.net == "" and row.function == "no remark"


def test_a_sheet_that_is_not_a_pin_table_is_reported_not_silently_dropped(sample: PinMap) -> None:
    assert sample.skipped_sheets == (("Summary of GPIO", "表头没有 Pin number / Netlist 列，不是引脚表"),)


def test_no_rows_says_where_it_looked_and_does_not_claim_absence(sample: PinMap) -> None:
    empty = sample.find("IMU")

    assert not empty.found
    assert "3 行" in empty.why_empty(), "the answer must say how much was searched"
    assert "Summary of GPIO" in empty.why_empty(), "the skipped sheet must be admitted"
    assert "不是硬件确认不存在" in empty.why_empty()


def test_a_missing_pin_says_the_same_thing(sample: PinMap) -> None:
    assert "查询无结果" in sample.by_pin("P99.9").why_empty()


def test_reading_the_same_file_twice_gives_the_same_thing(sample: PinMap) -> None:
    again = PinMap.load(sample.doc)

    assert again.rows == sample.rows and again.doc_sha256 == sample.doc_sha256


def test_each_device_sheet_keeps_its_own_identity(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "two.xlsx", {
        "MCU-X": pins([["1", "A1", "P0.1", "GPIO", "NET_A", "", ""]]),
        "BLE-Y": pins([["1", "Z9", "P12", "GPIO", "NET_B", "", ""]]),
    })

    table = PinMap.load(path)

    assert table.devices == ("MCU-X", "BLE-Y")
    assert {row.device for row in table.find("NET").rows} == {"MCU-X", "BLE-Y"}


def test_finding_by_function_text_works_when_the_net_name_is_cryptic(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "f.xlsx", {"MCU-X": pins([["1", "A1", "P0.1", "I2C", "IIC1", "Fuel gauge I2C", ""]])})

    assert PinMap.load(path).find("fuel gauge").found


# --------------------------------------------------------------- real hardware data


@pytest.mark.skipif(not REAL_MAP.exists(), reason="customer IO map is not in the repo")
def test_the_real_customer_io_map_reads() -> None:
    table = PinMap.load(REAL_MAP)

    assert len(table.devices) == 2, "one pin table per chip, plus a summary sheet"
    assert len(table.rows) > 60 and not table.problems
    spi = table.find("SPI")
    assert spi.found and all(row.pin_type == "SPI" for row in spi.rows)


@pytest.mark.skipif(not REAL_MAP.exists(), reason="customer IO map is not in the repo")
def test_a_peripheral_that_is_not_in_the_map_is_reported_as_such() -> None:
    """Not a failure of the reader - but it must not come back as a confident nothing."""
    empty = PinMap.load(REAL_MAP).find("IMU")

    if not empty.found:
        assert "查" in empty.why_empty() or "找不到" in empty.why_empty()

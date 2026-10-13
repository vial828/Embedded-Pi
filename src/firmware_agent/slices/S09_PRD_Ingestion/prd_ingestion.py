from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


_USER_STORY_HEADER_RE = re.compile(r"^User Story:\s*(.+?)\s*$")
_USER_STORY_ID_RE = re.compile(r"\bUser Story\s+(\d+)\b", re.IGNORECASE)
_PAGE_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+\s*$")
_PAGE_FOOTER_RE = re.compile(r"Page\s+(\d+)\s+of\s+\d+\s*$")
_AZURE_WI_ID_RE = re.compile(r"/edit/(\d+)(?:[/?#].*)?$")
# Source typo included: the export contains both "Please refer to" and "Pease refer to".
_STUB_RE = re.compile(r"^\s*p[l]?ease refer to\b", re.IGNORECASE)
_DOC_TITLE = "ADO User Story Export"
_DOCX_EXTS = {".docx", ".docm", ".dotx", ".dotm"}
_PDF_EXTS = {".pdf"}
_MD_EXTS = {".md", ".markdown", ".mdown"}


def _is_noise_line(text: str) -> bool:
    """Running header/footer noise that the ADO export repeats on every page.

    The footer repeats the story title, e.g. ``User Story: RDP on Set  Page 7 of 37``.
    Treated as a story header it fabricates a content-less duplicate, so it must be
    dropped before header matching.
    """
    if text == _DOC_TITLE:
        return True
    if _PAGE_RE.match(text):
        return True
    return bool(_PAGE_FOOTER_RE.search(text))


def _advance_page(text: str, current: int) -> int:
    """A footer closes a page, so following content belongs to the next page."""
    match = _PAGE_FOOTER_RE.search(text)
    return int(match.group(1)) + 1 if match else current


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout


def _extract_pdf_story_ids(pdf_path: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["pdftohtml", "-stdout", "-xml", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    story_ids: list[str] = []
    for line in result.stdout.splitlines():
        if "User Story:" not in line or "href=\"" not in line:
            continue
        href_match = re.search(r'href="([^"]+)"', line)
        if not href_match:
            continue
        wi_match = _AZURE_WI_ID_RE.search(href_match.group(1))
        if wi_match:
            story_ids.append(f"US-{int(wi_match.group(1)):07d}")
    return story_ids


def _extract_docx_text(docx_path: Path) -> str:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice:
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        try:
            subprocess.run(
                [
                    libreoffice,
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    str(tmpdir_path),
                    str(docx_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return ""
        txt_path = tmpdir_path / f"{docx_path.stem}.txt"
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8", errors="ignore")
        for candidate in tmpdir_path.glob("*.txt"):
            return candidate.read_text(encoding="utf-8", errors="ignore")
    return ""


def _read_text_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _PDF_EXTS:
        return _extract_pdf_text(path)
    if suffix in _DOCX_EXTS:
        return _extract_docx_text(path)
    if suffix in _MD_EXTS:
        return path.read_text(encoding="utf-8")
    return ""


def _normalize_block_text(lines: list[str]) -> str:
    cleaned: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or _is_noise_line(text):
            continue
        cleaned.append(text)
    return " ".join(cleaned).strip()


def _extract_user_story_id(*texts: str) -> str | None:
    for text in texts:
        for pattern in (_USER_STORY_ID_RE, _AZURE_WI_ID_RE):
            match = pattern.search(text)
            if match:
                return f"US-{int(match.group(1)):07d}"
    return None


def _is_cross_reference_stub(item: dict) -> bool:
    """True for ADO placeholder entries that only point at another work item.

    The export lists some stories twice: once in full, once as a bare
    ``please refer to User Story 2258111: FW Encryption`` (or a ``/edit/<id>`` URL in the
    acceptance criteria). The placeholder is the only carrier of the work-item id.
    """
    description = item.get("description", "").strip()
    if _STUB_RE.match(description):
        return True
    if not description:
        return any(_STUB_RE.match(line.strip()) for line in item.get("acceptance_criteria", []))
    return False


def _parse_user_stories(text: str, source: Path, story_ids: list[str] | None = None) -> list[dict]:
    requirements: list[dict] = []
    lines = text.splitlines()
    i = 0
    rid = 1
    story_index = 0
    page = 1
    source_rel = str(source).replace("\\", "/")

    while i < len(lines):
        current = lines[i].strip()

        if _is_noise_line(current):
            page = _advance_page(current, page)
            i += 1
            continue

        match = _USER_STORY_HEADER_RE.match(current)
        if not match:
            i += 1
            continue

        title = match.group(1).strip()
        story_page = page
        i += 1
        description_lines: list[str] = []
        acceptance_lines: list[str] = []
        section = ""

        while i < len(lines):
            current = lines[i].strip()
            if _is_noise_line(current):
                page = _advance_page(current, page)
                i += 1
                continue
            if _USER_STORY_HEADER_RE.match(current):
                break
            if current == "Description:":
                section = "description"
                i += 1
                continue
            if current == "Acceptance Criteria:":
                section = "acceptance"
                i += 1
                continue

            if section == "description":
                description_lines.append(lines[i])
            elif section == "acceptance":
                acceptance_lines.append(lines[i])
            i += 1

        description = _normalize_block_text(description_lines)
        acceptance_criteria = [line.strip() for line in acceptance_lines if line.strip()]
        # Prefer the id stated in the story text: positional matching against pdftohtml
        # links also counts table-of-contents links, which shifts every index.
        user_story_id = _extract_user_story_id(title, description, *acceptance_criteria)
        if not user_story_id and story_ids and story_index < len(story_ids):
            user_story_id = story_ids[story_index]
        story_index += 1
        requirements.append(
            {
                "req_id": f"R-{rid:03d}",
                "title": title,
                "description": description,
                "acceptance_criteria": acceptance_criteria,
                "user_story_id": user_story_id,
                "source": source_rel,
                "page": story_page,
            }
        )
        rid += 1

    return _merge_cross_reference_stubs(_drop_footer_echoes(requirements))


def _merge_cross_reference_stubs(requirements: list[dict]) -> list[dict]:
    """Fold ``please refer to`` placeholders into the story they point at.

    Keeps the work-item id (and nothing else) from the placeholder. A placeholder whose
    story is absent from this export is kept, since it is the only record of that need.
    """
    real_by_title: dict[str, dict] = {}
    for item in requirements:
        if not _is_cross_reference_stub(item):
            real_by_title.setdefault(item["title"], item)

    kept: list[dict] = []
    for item in requirements:
        if not _is_cross_reference_stub(item):
            kept.append(item)
            continue

        target = real_by_title.get(item["title"])
        if target is None:
            kept.append(item)
            continue
        if item["user_story_id"] and not target["user_story_id"]:
            target["user_story_id"] = item["user_story_id"]

    for index, item in enumerate(kept, 1):
        item["req_id"] = f"R-{index:03d}"
    return kept


def _drop_footer_echoes(requirements: list[dict]) -> list[dict]:
    """Drop entries that only echo the previous story title without any content."""
    kept: list[dict] = []
    for item in requirements:
        if (
            kept
            and item["title"] == kept[-1]["title"]
            and not item["description"]
            and not item["acceptance_criteria"]
        ):
            continue
        kept.append(item)

    for index, item in enumerate(kept, 1):
        item["req_id"] = f"R-{index:03d}"
    return kept


def _discover_prd_sources(prd_dir: Path) -> list[Path]:
    if not prd_dir.exists():
        return []
    priority = {".pdf": 0, ".docx": 1, ".docm": 1, ".dotx": 1, ".dotm": 1, ".md": 2, ".markdown": 2, ".mdown": 2}
    candidates = [p for p in prd_dir.iterdir() if p.is_file() and p.suffix.lower() in priority]
    return sorted(candidates, key=lambda p: (priority.get(p.suffix.lower(), 99), p.name.lower()))


def ingest_prd(docs_root: Path) -> Path:
    out = docs_root / "ai-generation" / "knowledge" / "requirements_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    prd_dir = docs_root / "prd"
    reqs: list[dict] = []
    selected_source: Path | None = None

    for source in _discover_prd_sources(prd_dir):
        text = _read_text_source(source)
        if not text:
            continue
        if source.suffix.lower() in _PDF_EXTS:
            reqs = _parse_user_stories(text, source, story_ids=_extract_pdf_story_ids(source))
        elif source.suffix.lower() in _DOCX_EXTS:
            reqs = _parse_user_stories(text, source)
        else:
            rid = 1
            for line in text.splitlines():
                item = line.strip()
                if not item or item.startswith("#"):
                    continue
                reqs.append(
                    {
                        "req_id": f"R-{rid:03d}",
                        "title": item,
                        "description": item,
                        "acceptance_criteria": [],
                        "user_story_id": _extract_user_story_id(item),
                        "source": str(source).replace("\\", "/"),
                        "page": None,
                    }
                )
                rid += 1
        if reqs:
            selected_source = source
            break

    out.write_text(
        json.dumps({"version": "0.1", "requirements": reqs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out

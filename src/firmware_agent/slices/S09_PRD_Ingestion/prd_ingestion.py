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


_HEADER_LINK_RE = re.compile(r'<a href="https://[^"]*/edit/(\d+)"><b>User Story:\s*(.*?)</b></a>', re.DOTALL)


def _normalize_story_title(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("&amp;", "&").replace("&#39;", "'")).strip()


def _extract_pdf_story_headers(pdf_path: Path) -> list[dict[str, str]]:
    """Work-item id and title of every story header, in document order.

    The bold header link is the only authoritative carrier of a story's own id. The story
    *text* contains ids too - but those are cross-references to *other* work items, and
    taking an id from the text is how a placeholder ended up wearing the id of the story it
    points at, silently deleting its own work item from the index.
    """
    try:
        result = subprocess.run(
            ["pdftohtml", "-stdout", "-xml", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return [
        {"user_story_id": f"US-{int(wi):07d}", "title": _normalize_story_title(title)}
        for wi, title in _HEADER_LINK_RE.findall(result.stdout)
    ]


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


def _parse_user_stories(text: str, source: Path, story_headers: list[dict[str, str]] | None = None) -> list[dict]:
    requirements: list[dict] = []
    lines = text.splitlines()
    i = 0
    rid = 1
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
        requirements.append(
            {
                "req_id": f"R-{rid:03d}",
                "title": title,
                "description": description,
                "acceptance_criteria": acceptance_criteria,
                "user_story_id": None,
                "source": source_rel,
                "page": story_page,
            }
        )
        rid += 1

    requirements = _drop_footer_echoes(requirements)
    _assign_story_ids(requirements, story_headers or [])
    return _annotate_cross_references(requirements)


def _assign_story_ids(requirements: list[dict], headers: list[dict[str, str]]) -> None:
    """Give every requirement the id of its own story header.

    Matching is monotonic in both lists (document order), with a short look-ahead for
    headers the text extraction dropped. A title that matches nothing keeps whatever id its
    own text states and is marked, because a wrong id is worse than a flagged one: a wrong
    id silently merges two work items' evidence, and nothing downstream can tell.
    """
    cursor = 0
    for item in requirements:
        title = _normalize_story_title(item["title"])
        match_at = None
        for candidate in range(cursor, min(cursor + 4, len(headers))):
            if headers[candidate]["title"] == title:
                match_at = candidate
                break
        if match_at is not None:
            item["user_story_id"] = headers[match_at]["user_story_id"]
            item["id_source"] = "story-header"
            cursor = match_at + 1
        else:
            item["user_story_id"] = _extract_user_story_id(item["title"], item["description"], *item["acceptance_criteria"])
            item["id_source"] = "story-text" if item["user_story_id"] else "none"
            item["id_unmatched"] = True


def _annotate_cross_references(requirements: list[dict]) -> list[dict]:
    """Keep every work item, and record where a placeholder points.

    A story whose whole description is "please refer to User Story 2258143" is still a work
    item the customer tracks. Folding them away - which an earlier revision did - made 32 of
    145 work items vanish from the index: content deduplication is fine, identity loss is
    not. So the record stays, carrying its own id, the literal reference text, and `refers_to`
    so coverage can follow the pointer instead of inventing evidence.
    """
    for item in requirements:
        if not _is_cross_reference_stub(item):
            continue
        item["origin"] = "reference"
        target = _extract_user_story_id(item["description"], *item["acceptance_criteria"])
        if target and target != item["user_story_id"]:
            item["refers_to"] = target
    return requirements


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
            reqs = _parse_user_stories(text, source, story_headers=_extract_pdf_story_headers(source))
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

from pathlib import Path

from firmware_agent.slices.S09_PRD_Ingestion.prd_ingestion import _parse_user_stories

_SOURCE = Path("Docs/prd/export.pdf")

# Mimics `pdftotext -layout` output of an ADO user-story export: every page repeats a
# footer that echoes the page's story title, plus a running document title header.
_EXPORT = """ADO User Story Export

   User Story: Power On/Off
   Description:
   As a user I want to turn the device on and off.

   Acceptance Criteria:
   Device turns on.
   Device turns off.

User Story: RDP on Set  Page 7 of 37
ADO User Story Export

   User Story: Clear Bluetooth Pairing
   Description:
   As a product engineer I want to clear any Bluetooth pairings.
   Acceptance Criteria:
   User issues a command to clear all paired devices.

User Story: Clear Bluetooth Pairing  Page 8 of 37
ADO User Story Export

   User Story: Legitimate FW Update
   Description:
   please refer to User Story 2258116: Legitimate FW Update
"""

# ADO lists some stories twice: once in full, once as a bare cross-reference placeholder.
# The placeholder is the only carrier of the Azure work-item id. Note the "Pease" typo and
# the variant that puts a /edit/<id> URL in the acceptance criteria instead of a description.
_STUBS = """ADO User Story Export

   User Story: FW Encryption
   Description:
   All bin files should be encrypted with AES key.
   Acceptance Criteria:
   Cipher text cannot be read in a hex editor.

   User Story: Debug Information Feature
   Description:
   As a developer I want to read the last error log.

   User Story: RDP on Set
   Description:
   Put the device into an irreversible RDP-on state.

   User Story: FW Encryption
   Description:
   please refer to User Story 2258111: FW Encryption

   User Story: Debug Information Feature
   Description:
   Pease refer to User Story 2258154: Debug Information Feature

   User Story: RDP on Set
   Acceptance Criteria:
   please refer to RDP on https://example.visualstudio.com/Adonis/_workitems/edit/2285096

   User Story: Orphan Placeholder
   Description:
   please refer to User Story 2258999: Orphan Placeholder
"""


def _titles(reqs: list[dict]) -> list[str]:
    return [r["title"] for r in reqs]


def _by_title(reqs: list[dict], title: str) -> list[dict]:
    return [r for r in reqs if r["title"] == title]


# --- running header / footer noise -------------------------------------------------


def test_page_footer_echoes_are_not_stories():
    assert _titles(_parse_user_stories(_EXPORT, _SOURCE)) == [
        "Power On/Off",
        "Clear Bluetooth Pairing",
        "Legitimate FW Update",
    ]


def test_footer_echo_does_not_split_acceptance_criteria():
    power = next(r for r in _parse_user_stories(_EXPORT, _SOURCE) if r["title"] == "Power On/Off")
    assert power["acceptance_criteria"] == ["Device turns on.", "Device turns off."]


def test_footer_echo_does_not_leak_into_description():
    clear = next(r for r in _parse_user_stories(_EXPORT, _SOURCE) if r["title"] == "Clear Bluetooth Pairing")
    assert "Page" not in clear["description"]
    assert "ADO User Story Export" not in clear["description"]


def test_source_and_page_are_recorded():
    clear = next(r for r in _parse_user_stories(_EXPORT, _SOURCE) if r["title"] == "Clear Bluetooth Pairing")
    assert clear["source"] == "Docs/prd/export.pdf"
    assert clear["page"] == 8


def test_req_ids_stay_sequential_after_filtering():
    assert [r["req_id"] for r in _parse_user_stories(_EXPORT, _SOURCE)] == ["R-001", "R-002", "R-003"]


# --- cross-reference placeholders --------------------------------------------------


def test_placeholder_entries_are_kept_as_their_own_work_items():
    """A placeholder is a tracked work item. Folding it away deleted 32 of 145 stories."""
    assert _titles(_parse_user_stories(_STUBS, _SOURCE)) == [
        "FW Encryption",
        "Debug Information Feature",
        "RDP on Set",
        "FW Encryption",
        "Debug Information Feature",
        "RDP on Set",
        "Orphan Placeholder",
    ]


def test_placeholder_typo_is_still_recognised():
    """The export contains both "Please refer to" and "Pease refer to"."""
    stubs = [r for r in _parse_user_stories(_STUBS, _SOURCE) if r.get("origin") == "reference"]
    assert len(stubs) == 4
    assert any("Pease" in r["description"] for r in stubs)


def test_a_placeholder_records_the_work_item_it_points_at():
    """Only the header layer can tell 'my id' from 'the id I point at'."""
    headers = [
        {"user_story_id": "US-2258111", "title": "FW Encryption"},
        {"user_story_id": "US-2258154", "title": "Debug Information Feature"},
        {"user_story_id": "US-2285096", "title": "RDP on Set"},
        {"user_story_id": "US-2325504", "title": "FW Encryption"},
        {"user_story_id": "US-2325542", "title": "Debug Information Feature"},
        {"user_story_id": "US-2325540", "title": "RDP on Set"},
        {"user_story_id": "US-2258999", "title": "Orphan Placeholder"},
    ]

    stubs = [r for r in _parse_user_stories(_STUBS, _SOURCE, story_headers=headers) if r.get("refers_to")]

    assert [r["refers_to"] for r in stubs] == ["US-2258111", "US-2258154", "US-2285096"]


def test_a_placeholder_without_header_links_admits_its_identity_is_uncertain():
    """No link layer means the only id in reach is the one being pointed at.

    That id is kept as a best guess, but the record says so. A guessed identity that
    presents itself as fact is how two work items end up sharing evidence.
    """
    stubs = [r for r in _parse_user_stories(_STUBS, _SOURCE) if r.get("origin") == "reference"]

    assert all(r["id_source"] == "story-text" and r["id_unmatched"] for r in stubs)
    assert all("refers_to" not in r for r in stubs), "we cannot tell its own id from its target's"


def test_work_item_url_in_a_description_is_a_reference_not_an_identity():
    """The variant that puts an /edit/<id> URL in the acceptance criteria."""
    parsed = _parse_user_stories(_STUBS, _SOURCE)
    real = next(r for r in parsed if r["title"] == "RDP on Set" and r.get("origin") != "reference")
    placeholder = next(r for r in parsed if r["title"] == "RDP on Set" and r.get("origin") == "reference")

    assert placeholder["origin"] == "reference"
    assert real["description"] == "Put the device into an irreversible RDP-on state."


def test_a_placeholder_keeps_its_own_work_item_id():
    """The header link is the authority for identity; the text mention is only a pointer."""
    headers = [
        {"user_story_id": "US-2258111", "title": "FW Encryption"},
        {"user_story_id": "US-2258154", "title": "Debug Information Feature"},
        {"user_story_id": "US-2285096", "title": "RDP on Set"},
        {"user_story_id": "US-2325504", "title": "FW Encryption"},
        {"user_story_id": "US-2325542", "title": "Debug Information Feature"},
        {"user_story_id": "US-2325540", "title": "RDP on Set"},
        {"user_story_id": "US-2258999", "title": "Orphan Placeholder"},
    ]

    reqs = _parse_user_stories(_STUBS, _SOURCE, story_headers=headers)

    assert [r["user_story_id"] for r in reqs] == [
        "US-2258111",
        "US-2258154",
        "US-2285096",
        "US-2325504",
        "US-2325542",
        "US-2325540",
        "US-2258999",
    ], "no two requirements may share an id, and no work item may go missing"
    assert reqs[3]["refers_to"] == "US-2258111"
    assert all(r["id_source"] == "story-header" for r in reqs)


def test_work_item_url_variant_is_recognised_as_a_placeholder():
    parsed = _parse_user_stories(_STUBS, _SOURCE)
    rdp_placeholders = [r for r in parsed if r["title"] == "RDP on Set" and r.get("origin") == "reference"]
    assert len(rdp_placeholders) == 1


def test_placeholder_keeps_real_story_content():
    fw = _by_title(_parse_user_stories(_STUBS, _SOURCE), "FW Encryption")[0]
    assert fw["description"] == "All bin files should be encrypted with AES key."
    assert fw["acceptance_criteria"] == ["Cipher text cannot be read in a hex editor."]


def test_placeholder_without_real_story_is_kept():
    """It is the only record of that need in this export, and it carries the work-item id."""
    orphan = _by_title(_parse_user_stories(_STUBS, _SOURCE), "Orphan Placeholder")
    assert len(orphan) == 1
    assert orphan[0]["user_story_id"] == "US-2258999"


def test_without_header_links_the_text_mention_is_the_only_id_available():
    """Docx/markdown sources have no link layer, so scraping is the fallback - and says so."""
    reqs = _parse_user_stories(_EXPORT, _SOURCE)
    fw = next(r for r in reqs if r["title"] == "Legitimate FW Update")
    assert fw["user_story_id"] == "US-2258116"
    assert fw["id_source"] == "story-text"


def test_header_links_beat_a_stale_positional_or_textual_id():
    """A wrong id silently merges two work items' evidence, so the header wins outright."""
    headers = [
        {"user_story_id": "US-1111111", "title": "Power On/Off"},
        {"user_story_id": "US-2222222", "title": "Clear Bluetooth Pairing"},
        {"user_story_id": "US-3333333", "title": "Legitimate FW Update"},
    ]

    reqs = _parse_user_stories(_EXPORT, _SOURCE, story_headers=headers)

    assert [r["user_story_id"] for r in reqs] == ["US-1111111", "US-2222222", "US-3333333"]
    assert reqs[2]["refers_to"] == "US-2258116", "the mentioned id survives as a pointer, not as identity"


def test_a_header_that_matches_nothing_is_flagged_not_guessed():
    headers = [{"user_story_id": "US-0000001", "title": "Something Else Entirely"}]

    reqs = _parse_user_stories(_EXPORT, _SOURCE, story_headers=headers)

    assert all(r.get("id_unmatched") for r in reqs)
    assert all(r["id_source"] in {"story-text", "none"} for r in reqs)

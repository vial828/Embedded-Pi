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


def test_placeholder_entries_are_folded_into_the_real_story():
    assert _titles(_parse_user_stories(_STUBS, _SOURCE)) == [
        "FW Encryption",
        "Debug Information Feature",
        "RDP on Set",
        "Orphan Placeholder",
    ]


def test_placeholder_typo_is_still_recognised():
    assert len(_by_title(_parse_user_stories(_STUBS, _SOURCE), "Debug Information Feature")) == 1


def test_placeholder_transfers_its_work_item_id():
    reqs = {r["title"]: r for r in _parse_user_stories(_STUBS, _SOURCE)}
    assert reqs["FW Encryption"]["user_story_id"] == "US-2258111"
    assert reqs["Debug Information Feature"]["user_story_id"] == "US-2258154"


def test_placeholder_work_item_url_is_used_as_id_source():
    reqs = {r["title"]: r for r in _parse_user_stories(_STUBS, _SOURCE)}
    assert reqs["RDP on Set"]["user_story_id"] == "US-2285096"


def test_placeholder_keeps_real_story_content():
    fw = _by_title(_parse_user_stories(_STUBS, _SOURCE), "FW Encryption")[0]
    assert fw["description"] == "All bin files should be encrypted with AES key."
    assert fw["acceptance_criteria"] == ["Cipher text cannot be read in a hex editor."]


def test_placeholder_without_real_story_is_kept():
    """It is the only record of that need in this export, and it carries the work-item id."""
    orphan = _by_title(_parse_user_stories(_STUBS, _SOURCE), "Orphan Placeholder")
    assert len(orphan) == 1
    assert orphan[0]["user_story_id"] == "US-2258999"


def test_text_mention_wins_over_positional_link_index():
    reqs = _parse_user_stories(_EXPORT, _SOURCE, story_ids=["US-9999999", "US-9999998", "US-9999997"])
    fw = next(r for r in reqs if r["title"] == "Legitimate FW Update")
    assert fw["user_story_id"] == "US-2258116"

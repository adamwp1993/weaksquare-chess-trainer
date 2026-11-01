from __future__ import annotations

from weaksquare.core.themes import GROUP_ORDER, display_name, humanize, info, is_valid_key


def test_known_and_unknown_themes() -> None:
    assert info("fork").group == "Motifs" and display_name("fork") == "Fork"
    assert info("mateIn1").name == "Mate in 1"
    assert info("long").group == "Lengths"
    new = info("brandNewTheme")
    assert new.group == "Other" and new.name == "Brand new theme"


def test_requirement_groups_exist() -> None:
    for group in ("Phases", "Motifs", "Advanced", "Mates", "Mate patterns", "Special moves", "Goals", "Origin"):
        assert group in GROUP_ORDER


def test_key_validation() -> None:
    assert is_valid_key("attackingF2F7")
    assert not is_valid_key("") and not is_valid_key("a b") and not is_valid_key("<x>")
    assert humanize("xRayAttack") == "X ray attack"

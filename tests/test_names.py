"""Catalog, validation, and the transactional claim rules."""

import pytest

from ghostpicker.auth import upsert_user
from ghostpicker.models import Ghost
from ghostpicker.models import Offer
from ghostpicker.models import User
from ghostpicker.names import ClaimError
from ghostpicker.names import available_names
from ghostpicker.names import claim_ghost
from ghostpicker.names import clean_person_name
from ghostpicker.names import draw_offer
from ghostpicker.names import format_phantom_name
from ghostpicker.names import person_name_error
from ghostpicker.seed import ensure_seeded
from ghostpicker.seed import load_catalog


def test_catalog_matches_the_sheet():
    rows = dict(load_catalog())
    assert len(rows) == 43
    assert "Bogle" in rows
    assert "Tom\u00e1s" in rows
    assert "Y\u016brei" in rows
    assert "Wiederg\u00e4nger" in rows
    assert rows["Pinky"] == ""
    assert rows["Inky"] == ""
    assert rows["Clyde"] == ""
    assert "Belushi" in rows["Slimer"]


def test_format_matches_the_brief():
    assert (
        format_phantom_name("Josua", "Bogle", "Pedersen")
        == "Josua \u201cBogle\u201d Pedersen"
    )


def test_person_name_rules():
    assert clean_person_name("  Ada   Lovelace ") == "Ada Lovelace"
    assert person_name_error("Ada", "first name") is None
    assert person_name_error("Jos\u00e9", "first name") is None
    assert person_name_error("O'Brien-Smith", "last name") is None
    assert person_name_error("", "first name") == "Enter a first name."
    assert person_name_error("...", "last name") == "Enter a last name."
    assert "40 characters" in person_name_error("A" * 41, "first name")
    assert person_name_error("Ada<script>", "first name")


def _user_id(email):
    return email.casefold()


def _offer(user_id, names, first="Ada", last="Lovelace"):
    upsert_user(user_id, user_id.split(":", 1)[-1])
    Offer(
        id=user_id,
        ghost_names=names,
        first_name=first,
        last_name=last,
    ).put()


def test_claim_is_unique_and_sticks(seeded):
    ada = _user_id("ada@example.com")
    grace = _user_id("grace@example.com")
    _offer(ada, ["Bogle", "Casper", "Zuul"])
    _offer(grace, ["Bogle", "Casper", "Zuul"], first="Grace", last="Hopper")

    phantom = claim_ghost(ada, "Bogle")
    assert phantom == "Ada \u201cBogle\u201d Lovelace"
    held = Ghost.get_by_id("Bogle")
    assert held.owner_id == ada
    assert held.owner_email == "ada@example.com"
    assert held.owner_first == "Ada"
    assert held.owner_last == "Lovelace"
    assert User.get_by_id(ada).ghost_name == "Bogle"

    with pytest.raises(ClaimError) as caught:
        claim_ghost(grace, "Bogle")
    assert caught.value.reason == "taken"
    assert Ghost.get_by_id("Bogle").owner_id == ada
    assert User.get_by_id(ada).ghost_name == "Bogle"


def test_change_releases_the_previous_name(seeded):
    ada = _user_id("ada@example.com")
    _offer(ada, ["Bogle"])
    claim_ghost(ada, "Bogle")
    _offer(ada, ["Casper"])
    claim_ghost(ada, "Casper")

    assert Ghost.get_by_id("Bogle").owner_id is None
    assert Ghost.get_by_id("Casper").owner_email == "ada@example.com"
    assert User.get_by_id(ada).ghost_name == "Casper"


def test_claim_rejects_a_name_outside_the_offer(seeded):
    ada = _user_id("ada@example.com")
    _offer(ada, ["Bogle"])
    with pytest.raises(ClaimError) as caught:
        claim_ghost(ada, "Casper")
    assert caught.value.reason == "invalid_offer"
    assert Ghost.get_by_id("Casper").owner_id is None


def test_draw_skips_taken_names_and_the_current_name(seeded):
    ada = _user_id("ada@example.com")
    bogle = Ghost.get_by_id("Bogle")
    bogle.owner_id = "someone-else"
    bogle.put()

    free = available_names(exclude_name="Casper")
    assert "Bogle" not in free
    assert "Casper" not in free
    assert "Zuul" in free

    chosen = draw_offer(ada, "Ada", "Lovelace", exclude_name="Casper")
    assert "Bogle" not in chosen
    assert "Casper" not in chosen
    assert len(chosen) == 3


def test_draw_returns_fewer_names_when_the_catalog_is_nearly_full(seeded):
    ada = _user_id("ada@example.com")
    for name in available_names()[2:]:
        ghost = Ghost.get_by_id(name)
        ghost.owner_id = "held"
        ghost.put()
    chosen = draw_offer(ada, "Ada", "Lovelace")
    assert len(chosen) == 2
    for name in chosen:
        ghost = Ghost.get_by_id(name)
        ghost.owner_id = "held"
        ghost.put()
    assert draw_offer(ada, "Ada", "Lovelace") == []


def test_seed_does_not_wipe_an_existing_claim(app):
    with app.ndb_client.context():
        ensure_seeded(app.ndb_client)
        ghost = Ghost.get_by_id("Bogle")
        ghost.owner_id = "someone"
        ghost.owner_email = "ada@example.com"
        ghost.owner_first = "Ada"
        ghost.owner_last = "Lovelace"
        ghost.put()
        app.ndb_client.ghosts_seeded = False
        ensure_seeded(app.ndb_client)
        again = Ghost.get_by_id("Bogle")
        assert again.owner_email == "ada@example.com"
        assert len(Ghost.query().fetch()) == 43

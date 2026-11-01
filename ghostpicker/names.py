"""Draw phantom names and claim one without giving it to two people."""

import random

from google.api_core import exceptions as core_exceptions
from google.cloud import ndb

from ghostpicker.models import Ghost
from ghostpicker.models import Offer
from ghostpicker.models import User

_MAX_NAME_LENGTH = 40
_OFFER_SIZE = 3
_OPEN_QUOTE = "\u201c"
_CLOSE_QUOTE = "\u201d"
_ALLOWED_MARKS = " .'-\u2019"


class ClaimError(Exception):
    """The user could not take the ghost name they chose.

    Attributes:
        reason: Short code. One of "invalid_offer", "taken", "conflict".
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def format_phantom_name(first, ghost, last):
    """Build the public form of a phantom name.

    Args:
        first: The first name the user typed.
        ghost: The catalog ghost name.
        last: The last name the user typed.

    Returns:
        A string such as Josua “Bogle” Pedersen.
    """
    return f"{first} {_OPEN_QUOTE}{ghost}{_CLOSE_QUOTE} {last}"


def clean_person_name(value):
    """Collapse whitespace in a typed name.

    Args:
        value: Raw form input, or None.

    Returns:
        The cleaned name, or an empty string.
    """
    if value is None:
        return ""
    return " ".join(str(value).split())


def person_name_error(value, label):
    """Return an error message for a first or last name, or None.

    Args:
        value: A name that has already been passed through
            clean_person_name.
        label: "first name" or "last name", used in the message.
    """
    if not value or not any(char.isalnum() for char in value):
        return f"Enter a {label}."
    if len(value) > _MAX_NAME_LENGTH:
        return f"Use 40 characters or fewer for the {label}."
    for char in value:
        if char.isalnum() or char in _ALLOWED_MARKS:
            continue
        return (
            f"The {label} can use letters, numbers, spaces, "
            "apostrophes, periods, or hyphens."
        )
    return None


def available_names(exclude_name=None):
    """Return ghost names nobody currently holds.

    Args:
        exclude_name: A name to leave out even if it looks free. Used so
            a person who is changing names is not offered the one they
            already hold.

    Returns:
        A list of ghost name strings, sorted for stable draws.
    """
    names = []
    for ghost in Ghost.query().fetch():
        name = ghost.key.id()
        if not name or ghost.owner_id:
            continue
        if exclude_name and name == exclude_name:
            continue
        names.append(name)
    names.sort(key=str.casefold)
    return names


def draw_offer(user_id, first, last, exclude_name=None):
    """Store a fresh offer of up to three free ghost names.

    Args:
        user_id: Datastore id of the signed-in user.
        first: Cleaned first name.
        last: Cleaned last name.
        exclude_name: See available_names.

    Returns:
        The list of offered names, or an empty list when none are free.
    """
    pool = available_names(exclude_name=exclude_name)
    if not pool:
        _delete_offer(user_id)
        return []
    chosen = random.sample(pool, min(_OFFER_SIZE, len(pool)))
    Offer(
        id=user_id,
        ghost_names=chosen,
        first_name=first,
        last_name=last,
    ).put()
    return chosen


def _delete_offer(user_id):
    offer = Offer.get_by_id(user_id)
    if offer is not None:
        offer.key.delete()


def claim_ghost(user_id, ghost_name):
    """Give one offered ghost name to a user, releasing any previous one.

    The whole update is one Datastore transaction. Two people can be
    shown the same name; only the first commit keeps it. A lost race
    retries immediately. Datastore's own retry sleeps for a second, so
    contention is retried here instead.

    Args:
        user_id: Datastore id of the signed-in user.
        ghost_name: The catalog name the user selected.

    Returns:
        The formatted phantom name now stored for the user.

    Raises:
        ClaimError: The offer is missing or stale, another user already
            holds the name, or three attempts lose a race.
    """
    for _ in range(3):
        try:
            return _claim_once(user_id, ghost_name)
        except core_exceptions.Aborted:
            continue
    raise ClaimError("conflict")


@ndb.transactional(retries=0)
def _claim_once(user_id, ghost_name):
    """Run one attempt of claim_ghost inside a transaction."""
    offer = Offer.get_by_id(user_id)
    if offer is None or ghost_name not in list(offer.ghost_names):
        raise ClaimError("invalid_offer")
    ghost = Ghost.get_by_id(ghost_name)
    user = User.get_by_id(user_id)
    if ghost is None or user is None:
        raise ClaimError("invalid_offer")
    if ghost.owner_id and ghost.owner_id != user_id:
        raise ClaimError("taken")

    previous = user.ghost_name
    if previous and previous != ghost_name:
        old = Ghost.get_by_id(previous)
        if old is not None and old.owner_id == user_id:
            old.owner_id = None
            old.owner_email = None
            old.owner_first = None
            old.owner_last = None
            old.put()

    ghost.owner_id = user_id
    ghost.owner_email = user.email
    ghost.owner_first = offer.first_name
    ghost.owner_last = offer.last_name
    ghost.put()
    user.first_name = offer.first_name
    user.last_name = offer.last_name
    user.ghost_name = ghost_name
    user.put()
    offer.key.delete()
    return format_phantom_name(
        offer.first_name, ghost_name, offer.last_name
    )

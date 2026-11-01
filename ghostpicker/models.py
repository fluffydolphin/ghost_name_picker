"""Datastore models for the ghost catalog, users, and name offers."""

from google.cloud import ndb


class Ghost(ndb.Model):
    """One catalog ghost name, and the person who holds it if it is taken.

    The entity id is the ghost name.
    """

    description = ndb.TextProperty()
    owner_id = ndb.StringProperty()
    owner_email = ndb.StringProperty()
    owner_first = ndb.StringProperty()
    owner_last = ndb.StringProperty()


class User(ndb.Model):
    """A signed-in person.

    The entity id is the Google subject id.
    """

    email = ndb.StringProperty(required=True)
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    ghost_name = ndb.StringProperty()


class Offer(ndb.Model):
    """The names currently offered to one user.

    The entity id matches the user's id. A new draw overwrites the previous
    offer. Refreshing the results page reads this entity, so the three names
    stay put until the user submits the form again or claims one.
    """

    ghost_names = ndb.StringProperty(repeated=True)
    first_name = ndb.StringProperty(required=True)
    last_name = ndb.StringProperty(required=True)


class CatalogState(ndb.Model):
    """Records that the checked-in ghost catalog has been seeded."""

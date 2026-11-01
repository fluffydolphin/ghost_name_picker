"""Shared fixtures. Tests talk to the Datastore emulator.

Start the emulator with --consistency=1.0. Firestore in Datastore mode
answers every query with strong consistency, but the emulator defaults
to 0.9 and then sometimes leaves a fresh write out of a query.
"""

import os
import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.pop("GAE_ENV", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)


@pytest.fixture
def app(monkeypatch):
    """An application in its own Datastore namespace.

    The emulator is shared by every test. A fresh namespace keeps one
    test's claims from showing up in the next test.
    """
    monkeypatch.setenv("DATASTORE_NAMESPACE", uuid.uuid4().hex)
    from main import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded(app):
    """An open NDB context with the catalog loaded.

    Do not use the Flask test client inside a test that uses this
    fixture. A request opens its own context, and NDB allows only one.
    """
    from ghostpicker.seed import ensure_seeded

    with app.ndb_client.context():
        ensure_seeded(app.ndb_client)
        yield


def csrf_token(response):
    """Read the SeaSurf token out of a rendered form."""
    html = response.get_data(as_text=True)
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match, html
    return match.group(1)


def sign_in(client, email="ada@example.com", next_path="/"):
    """Create a user and session without calling Google.

    The browser sign-in is the Google redirect. Tests only need the same
    session key the callback writes after Google returns.
    """
    from ghostpicker.auth import upsert_user

    user_id = email.casefold()
    with client.application.ndb_client.context():
        upsert_user(user_id, email)
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return client.get(next_path)

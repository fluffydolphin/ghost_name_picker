"""Google sign-in."""

import hashlib
import os
from functools import wraps

import flask
import requests
from authlib.integrations.flask_client import OAuth

from ghostpicker.models import User

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_VERIFIED_CLIENTS = set()


def init_oauth(app):
    """Register the Google OpenID provider.

    Args:
        app: The Flask application.

    Raises:
        RuntimeError: The Google client id or secret is missing or Google
            rejects the pair. Sign-in cannot work, so the process stops.
    """
    client_id, client_secret = _google_credentials()
    oauth = OAuth(app)
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email"},
    )
    app.extensions["ghostpicker_oauth"] = oauth


def _google_credentials():
    """Return the Google client id and secret after checking them.

    Google is asked once, with a fake authorization code: a real
    client answers invalid_grant, and a bad id or secret answers
    invalid_client.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required."
        )
    _verify_google_client(client_id, client_secret)
    return client_id, client_secret


def _verify_google_client(client_id, client_secret):
    """Confirm Google accepts this client id and secret."""
    digest = hashlib.sha256(
        f"{client_id}\n{client_secret}".encode("utf-8")
    ).hexdigest()
    if digest in _VERIFIED_CLIENTS:
        return
    try:
        response = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": "invalid",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not reach Google to verify the OAuth client."
        ) from exc
    error = ""
    if response.headers.get("content-type", "").startswith("application/json"):
        error = response.json().get("error", "")
    if error == "invalid_grant":
        _VERIFIED_CLIENTS.add(digest)
        return
    if error == "invalid_client" or response.status_code == 401:
        raise RuntimeError(
            "Google rejected GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET."
        )
    raise RuntimeError(
        "Could not verify the Google OAuth client "
        f"({error or response.status_code})."
    )


def oauth_client(app):
    """Return the Authlib client stored on the app."""
    return app.extensions["ghostpicker_oauth"]


def upsert_user(user_id, email):
    """Create the user record, or refresh the stored email.

    Args:
        user_id: The Google subject id.
        email: Address to show on the overview page.

    Returns:
        The User entity.
    """
    user = User.get_or_insert(user_id, email=email)
    if user.email != email:
        user.email = email
        user.put()
    return user


def safe_next(value):
    """Return a same-site path, or the overview path.

    Browsers read a backslash as a slash and ignore tabs and newlines, so
    a path that only looks local can still send the user to another site.
    Values containing either are refused.

    Args:
        value: A path from the query string or a hidden form field.
    """
    if (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and value.isprintable()
    ):
        return value
    return flask.url_for("overview")


def login_required(view):
    """Redirect anonymous visitors to the sign-in page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if flask.g.user is None:
            return flask.redirect(
                flask.url_for("login", next=flask.request.path)
            )
        return view(*args, **kwargs)

    return wrapped

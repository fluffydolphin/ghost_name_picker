"""HTTP flow: sign in, draw, claim, and see the same name again."""

import re

import pytest

from tests.conftest import csrf_token
from tests.conftest import sign_in
from ghostpicker.auth import safe_next
from ghostpicker.models import Ghost
from ghostpicker.names import format_phantom_name


def _radios(html):
    return re.findall(r'name="ghost_name" value="([^"]+)"', html)


def test_favicon_is_the_project_png(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_overview_lists_the_catalog_for_anonymous_visitors(client):
    page = client.get("/")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Get a Phantom name" in body
    assert "Change your current Phantom name" not in body
    assert "Bogle" in body
    assert "Zuul" in body


def test_choosing_a_name_requires_sign_in(client):
    response = client.get("/pick")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_offers_google_only(client):
    page = client.get("/login")
    body = page.get_data(as_text=True)
    assert "Sign in with Google" in body
    assert "Sign in locally" not in body
    assert client.get("/dev-login").status_code == 404


def test_cancelled_google_sign_in_returns_to_login(client):
    for query in ("error=access_denied&state=x", "code=used&state=stale"):
        page = client.get(f"/auth/callback?{query}", follow_redirects=True)
        assert page.request.path == "/login"
        assert "Google sign-in did not finish" in page.get_data(as_text=True)


def test_next_only_allows_paths_on_this_site(app):
    off_site = [
        "https://evil.com",
        "//evil.com",
        "/\\evil.com",
        "/\t/evil.com",
    ]
    with app.test_request_context():
        assert safe_next("/pick") == "/pick"
        for value in off_site:
            assert safe_next(value) == "/"


def test_startup_fails_without_google_credentials(monkeypatch):
    import main

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        main.create_app()


def test_startup_fails_when_google_rejects_the_secret(monkeypatch):
    import main
    from ghostpicker import auth

    monkeypatch.setenv(
        "GOOGLE_CLIENT_ID", "missing-client.apps.googleusercontent.com"
    )
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "not-a-real-secret")
    auth._VERIFIED_CLIENTS.clear()
    with pytest.raises(RuntimeError, match="rejected"):
        main.create_app()


def test_blank_and_rejected_names(client):
    sign_in(client, next_path="/pick")
    form = client.get("/pick")
    rejected = client.post(
        "/pick",
        data={
            "first_name": "Ada<script>",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
    )
    assert rejected.status_code == 400
    assert "first name" in rejected.get_data(as_text=True)


def test_claim_shows_the_same_name_to_a_returning_user(app):
    ada = app.test_client()
    sign_in(ada, "ada@example.com", next_path="/pick")
    form = ada.get("/pick")
    drawn = ada.post(
        "/pick",
        data={
            "first_name": "  Ada  ",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
        follow_redirects=True,
    )
    assert drawn.status_code == 200
    html = drawn.get_data(as_text=True)
    choices = _radios(html)
    assert 1 <= len(choices) <= 3
    chosen = choices[0]
    claimed = ada.post(
        "/results",
        data={"ghost_name": chosen, "_csrf_token": csrf_token(drawn)},
        follow_redirects=True,
    )
    phantom = format_phantom_name("Ada", chosen, "Lovelace")
    body = claimed.get_data(as_text=True)
    assert phantom in body
    assert "ada@example.com" in body
    assert "Ada Lovelace" in body
    assert "Change your current Phantom name" in body

    again = ada.get("/")
    assert phantom in again.get_data(as_text=True)

    grace = app.test_client()
    sign_in(grace, "grace@example.com", next_path="/pick")
    grace_form = grace.get("/pick")
    grace_draw = grace.post(
        "/pick",
        data={
            "first_name": "Grace",
            "last_name": "Hopper",
            "_csrf_token": csrf_token(grace_form),
        },
        follow_redirects=True,
    )
    assert chosen not in _radios(grace_draw.get_data(as_text=True))
    register = grace.get("/").get_data(as_text=True)
    assert "ada@example.com" in register
    assert "Ada Lovelace" in register


def test_a_name_outside_the_offer_is_refused(app):
    client = app.test_client()
    sign_in(client, next_path="/pick")
    form = client.get("/pick")
    drawn = client.post(
        "/pick",
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
        follow_redirects=True,
    )
    refused = client.post(
        "/results",
        data={
            "ghost_name": "Not A Ghost",
            "_csrf_token": csrf_token(drawn),
        },
        follow_redirects=True,
    )
    assert "Draw again" in refused.get_data(as_text=True)
    with app.ndb_client.context():
        assert Ghost.get_by_id("Bogle").owner_id is None


def test_changing_a_name_releases_the_old_one(app):
    client = app.test_client()
    sign_in(client, next_path="/pick")
    form = client.get("/pick")
    drawn = client.post(
        "/pick",
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
        follow_redirects=True,
    )
    first = _radios(drawn.get_data(as_text=True))[0]
    client.post(
        "/results",
        data={"ghost_name": first, "_csrf_token": csrf_token(drawn)},
        follow_redirects=True,
    )

    form = client.get("/pick")
    redrawn = client.post(
        "/pick",
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
        follow_redirects=True,
    )
    choices = _radios(redrawn.get_data(as_text=True))
    assert first not in choices
    second = choices[0]
    client.post(
        "/results",
        data={
            "ghost_name": second,
            "_csrf_token": csrf_token(redrawn),
        },
        follow_redirects=True,
    )
    with app.ndb_client.context():
        assert Ghost.get_by_id(first).owner_id is None
        assert Ghost.get_by_id(second).owner_email == "ada@example.com"


def test_refreshing_results_keeps_the_same_three(app):
    client = app.test_client()
    sign_in(client, next_path="/pick")
    form = client.get("/pick")
    drawn = client.post(
        "/pick",
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "_csrf_token": csrf_token(form),
        },
        follow_redirects=False,
    )
    assert drawn.status_code == 302
    first = client.get("/results")
    second = client.get("/results")
    assert _radios(first.get_data(as_text=True)) == _radios(
        second.get_data(as_text=True)
    )

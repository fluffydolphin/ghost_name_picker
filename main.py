"""Ghost Name Picker web application."""

import os
from pathlib import Path

from authlib.integrations.flask_client import OAuthError
import flask
import securescaffold
from werkzeug.middleware.proxy_fix import ProxyFix

from ghostpicker.auth import init_oauth
from ghostpicker.auth import login_required
from ghostpicker.auth import oauth_client
from ghostpicker.auth import safe_next
from ghostpicker.auth import upsert_user
from ghostpicker.client import create_ndb_client
from ghostpicker.models import Ghost
from ghostpicker.models import Offer
from ghostpicker.models import User
from ghostpicker.names import ClaimError
from ghostpicker.names import claim_ghost
from ghostpicker.names import clean_person_name
from ghostpicker.names import draw_offer
from ghostpicker.names import format_phantom_name
from ghostpicker.names import person_name_error
from ghostpicker.seed import ensure_seeded

_ROOT = Path(__file__).resolve().parent


class _NdbMiddleware:
    """Open one NDB context for each request."""

    def __init__(self, wsgi_app, client):
        self.wsgi_app = wsgi_app
        self.client = client

    def __call__(self, environ, start_response):
        with self.client.context():
            return self.wsgi_app(environ, start_response)


def create_app():
    """Build the Flask app, including security headers and Datastore."""
    os.environ["FLASK_SETTINGS_FILENAME"] = str(_ROOT / "settings.py")
    app = securescaffold.create_app(
        __name__,
        template_folder="ghostpicker/templates",
        static_folder="ghostpicker/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    # Allow plain http on local instance
    if os.environ.get("GAE_ENV") != "standard":
        app.talisman.force_https = False

    init_oauth(app)
    client = create_ndb_client()
    app.ndb_client = client
    app.wsgi_app = ProxyFix(
        _NdbMiddleware(app.wsgi_app, client),
        x_for=1,
        x_proto=1,
        x_host=1,
    )
    _register_routes(app)
    return app


def _register_routes(app):
    """Attach view functions to the application."""

    @app.context_processor
    def inject_user():
        return {"user": getattr(flask.g, "user", None)}

    @app.before_request
    def prepare_request():
        ensure_seeded(app.ndb_client)
        user_id = flask.session.get("user_id")
        user = User.get_by_id(user_id) if user_id else None
        if user_id and user is None:
            flask.session.pop("user_id", None)
        flask.g.user = user

    @app.get("/")
    def overview():
        """List every ghost name and who holds it."""
        user = flask.g.user
        ghosts = Ghost.query().fetch()
        ghosts.sort(key=lambda ghost: (ghost.key.id() or "").casefold())
        return flask.render_template(
            "overview.html",
            ghosts=ghosts,
            phantom=_phantom(user),
            current_name=user.ghost_name if user else None,
        )

    @app.get("/login")
    def login():
        """Show the Google sign-in button."""
        return flask.render_template(
            "login.html",
            next_path=safe_next(flask.request.args.get("next")),
        )

    @app.get("/login/google")
    def login_google():
        """Start the Google OpenID Connect redirect."""
        flask.session["next"] = safe_next(flask.request.args.get("next"))
        redirect_uri = flask.url_for("auth_callback", _external=True)
        return oauth_client(app).google.authorize_redirect(redirect_uri)

    @app.get("/auth/callback")
    def auth_callback():
        """Finish Google sign-in and store the user."""
        oauth = oauth_client(app)
        try:
            token = oauth.google.authorize_access_token()
        except OAuthError as exc:
            app.logger.warning("Google sign-in failed: %s", exc)
            flask.flash("Google sign-in did not finish. Try again.")
            return flask.redirect(
                flask.url_for("login", next=flask.session.pop("next", None))
            )
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = oauth.google.userinfo()
        email = userinfo.get("email")
        subject = userinfo.get("sub")
        if (
            not email
            or not subject
            or userinfo.get("email_verified", True) is False
        ):
            flask.abort(400)
        upsert_user(subject, email)
        destination = safe_next(flask.session.get("next"))
        flask.session["user_id"] = subject
        flask.session.pop("next", None)
        return flask.redirect(destination)

    @app.post("/logout")
    def logout():
        """Clear the signed-in session."""
        flask.session.pop("user_id", None)
        return flask.redirect(flask.url_for("overview"))

    @app.route("/pick", methods=["GET", "POST"])
    @login_required
    def pick():
        """Collect a first and last name, then draw three ghost names."""
        user = flask.g.user
        first = user.first_name or ""
        last = user.last_name or ""
        if flask.request.method == "POST":
            first = clean_person_name(flask.request.form.get("first_name"))
            last = clean_person_name(flask.request.form.get("last_name"))
            error = person_name_error(first, "first name") or (
                person_name_error(last, "last name")
            )
            if error:
                return _name_form(user, first, last, error), 400
            chosen = draw_offer(
                user.key.id(),
                first,
                last,
                exclude_name=user.ghost_name,
            )
            if not chosen:
                return (
                    _name_form(
                        user,
                        first,
                        last,
                        "Every ghost name is already taken.",
                    ),
                    409,
                )
            return flask.redirect(flask.url_for("results"))
        return _name_form(user, first, last, None)

    @app.route("/results", methods=["GET", "POST"])
    @login_required
    def results():
        """Show the current offer and claim the name the user picks."""
        user = flask.g.user
        offer = Offer.get_by_id(user.key.id())
        if offer is None:
            flask.flash("Enter your name to draw phantom names.")
            return flask.redirect(flask.url_for("pick"))
        error = None
        status = 200
        if flask.request.method == "POST":
            ghost_name = flask.request.form.get("ghost_name", "")
            try:
                claim_ghost(user.key.id(), ghost_name)
            except ClaimError as exc:
                if exc.reason in ("taken", "conflict"):
                    error = (
                        "That phantom name was just taken. Choose another."
                    )
                    status = 409
                else:
                    flask.flash("Those choices have expired. Draw again.")
                    return flask.redirect(flask.url_for("pick"))
            else:
                return flask.redirect(flask.url_for("overview"))
            offer = Offer.get_by_id(user.key.id()) or offer
        options = _offer_options(offer, user)
        return (
            flask.render_template(
                "results.html",
                options=options,
                error=error,
                selectable=any(not option["taken"] for option in options),
            ),
            status,
        )

    @app.get("/favicon.ico")
    def favicon():
        """Serve the project icon. Browsers request this path by default."""
        return flask.send_file(
            _ROOT / "favicon-16x16.png",
            mimetype="image/png",
        )


def _phantom(user):
    if (
        user
        and user.ghost_name
        and user.first_name
        and user.last_name
    ):
        return format_phantom_name(
            user.first_name, user.ghost_name, user.last_name
        )
    return None


def _name_form(user, first, last, error):
    return flask.render_template(
        "form.html",
        error=error,
        first_name=first,
        last_name=last,
        phantom=_phantom(user),
    )


def _offer_options(offer, user):
    options = []
    for name in offer.ghost_names:
        ghost = Ghost.get_by_id(name)
        taken = bool(
            ghost
            and ghost.owner_id
            and ghost.owner_id != user.key.id()
        )
        description = ""
        if ghost is not None and ghost.description:
            description = ghost.description
        options.append(
            {
                "name": name,
                "label": format_phantom_name(
                    offer.first_name, name, offer.last_name
                ),
                "description": description,
                "taken": taken,
            }
        )
    return options


app = create_app()

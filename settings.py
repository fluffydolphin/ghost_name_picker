"""Flask settings loaded by the secure scaffold.

All-caps names are copied into the Flask config. Secrets come from the
environment. On a developer machine, a gitignored .env file is loaded
first. Variables already set in the shell are left alone. On App Engine
the file is not read; app.yaml supplies the environment.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_ON_APP_ENGINE = os.environ.get("GAE_ENV") == "standard"
if not _ON_APP_ENGINE:
    load_dotenv(Path(__file__).resolve().parent / ".env")
_secret = os.environ.get("SECRET_KEY", "")

if _secret:
    SECRET_KEY = _secret
elif not _ON_APP_ENGINE:
    SECRET_KEY = "local-development-secret"
else:
    # Empty lets the secure scaffold store a generated key in Datastore.
    SECRET_KEY = ""

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = _ON_APP_ENGINE
PREFERRED_URL_SCHEME = "https" if _ON_APP_ENGINE else "http"

CSRF_COOKIE_SECURE = _ON_APP_ENGINE
CSRF_COOKIE_HTTPONLY = True

# Static files are same-origin. No inline scripts or styles.
CSP_POLICY = {
    "default-src": "'none'",
    "script-src": "'self'",
    "style-src": "'self'",
    "img-src": "'self'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
    "connect-src": "'self'",
}

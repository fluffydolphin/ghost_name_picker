# Ghost Name Picker

A Flask app on Google App Engine that gives each signed-in user a unique
ghost name, shown as `First “Ghost” Last` (for example, Josua “Bogle”
Pedersen). Built for the PHQ Studios Intermediate Backend Developer test.

**Live app:** https://ghost-name-picker-513202.appspot.com/

## How it works

1. **Overview (`/`)** lists every ghost name in the catalog. Taken names show
   the email address and the first and last name of the person holding them.
   The button reads "Get a Phantom name", or "Change your current Phantom
   name" once you have one.
2. **Name form (`/pick`)** asks for a first and last name. You must sign in
   with Google first.
3. **Results (`/results`)** offers three random names that nobody holds.
   Choosing one claims it and returns you to the overview. The name stays
   yours, and is shown to you on every visit, until you change it.

## Design

### Request flow

App Engine serves the files in `ghostpicker/static` directly. Every other
request goes to gunicorn and then to the Flask app built in `main.py`:

1. `ProxyFix` trusts App Engine's forwarded headers, so Flask knows the
   request arrived over HTTPS and builds `https://` callback URLs.
2. A small WSGI middleware opens one NDB context per request, which every
   Datastore call needs.
3. A `before_request` hook loads the catalog on the first request (see
   below) and loads the signed-in user from the session.

| Route            | Method    | Purpose                               |
| ---------------- | --------- | ------------------------------------- |
| `/`              | GET       | Overview                              |
| `/login`         | GET       | Sign-in page                          |
| `/login/google`  | GET       | Redirects to Google                   |
| `/auth/callback` | GET       | Finishes sign-in                      |
| `/logout`        | POST      | Signs out                             |
| `/pick`          | GET, POST | Name form; a POST draws three names   |
| `/results`       | GET, POST | Shows the draw; a POST claims a name  |

### Data model

All data lives in Firestore in Datastore mode and is read and written with
`google.cloud.ndb`.

| Kind           | Key                       | Fields                                                              | Purpose                                                        |
| -------------- | ------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------- |
| `Ghost`        | The ghost name            | `description`, `owner_id`, `owner_email`, `owner_first`, `owner_last` | One per catalog name. The owner fields are set while it is taken. |
| `User`         | Google account id (`sub`) | `email`, `first_name`, `last_name`, `ghost_name`                     | A signed-in person and the name they hold.                     |
| `Offer`        | Same id as the user       | `ghost_names`, `first_name`, `last_name`                             | The names currently on that user's results page.               |
| `CatalogState` | `"ghosts"`                | none                                                                | Marks that the catalog has been loaded.                        |

The holder's email and name are copied onto `Ghost`, so the overview is a
single query with no joins.

### Keeping names unique

Datastore has no unique constraints, so the ghost name itself is the entity
key. Claiming a name (`names.claim_ghost`) runs in one transaction that:

1. Checks the chosen name is in the user's current offer.
2. Reads the `Ghost` and refuses if someone else holds it.
3. Releases the user's previous name, if they had one.
4. Writes the new holder on `Ghost`, the new name on `User`, and deletes the
   `Offer`.

If two people claim the same name at the same moment, only one transaction
can commit. The other is retried, finds the name taken, and that user sees
"That phantom name was just taken" with their remaining options. Because
releasing the old name and claiming the new one happen in the same
transaction, a user can never hold two names, and a change can never leave
them with none.

### Drawing three names

`names.draw_offer` picks three names at random from those nobody holds,
leaving out the user's current name, and saves them as an `Offer`. The form
uses POST-redirect-GET, so refreshing the results page shows the same three
names. Because the offer is stored, a user can only claim a name they were
actually shown. When fewer than three names are free, the page shows what is
left.

### Returning users

The claimed name is stored on the `User` entity, keyed by the Google account
id, so the same name appears every time that person signs in, on any device.
The form is pre-filled with the first and last name from their current
phantom name.

### The ghost catalog

The names come from the supplied spreadsheet, saved as `data/ghosts.csv`. On
the first request, `seed.ensure_seeded` inserts each name with
`get_or_insert`, which never overwrites an existing entity, so a restart or a
second instance cannot wipe a claim. It then writes the `CatalogState`
marker. Each process also remembers that the catalog is loaded, so later
requests skip the check.

### Sign-in

Google sign-in uses OpenID Connect through Authlib, with the `openid email`
scope. Authlib checks the `state` value and validates the ID token. The
session cookie, signed by Flask, holds the Google account id. Accounts
without a verified email are refused.

- `login_required` sends signed-out users to `/login` and remembers where
  they were going in `next`. `safe_next` only accepts paths on this site, so
  the parameter cannot be used to send someone to another site.
- A cancelled or failed sign-in returns to the login page with a message.
- At startup the app checks that the Google client id and secret are set and
  that Google accepts them. A missing or wrong secret stops the app from
  starting with a clear error, rather than failing at the first login.

### Security

- **Secure scaffold:** `securescaffold.create_app` adds Flask-Talisman (HTTPS
  redirect, HSTS, Content Security Policy, frame and content-type headers)
  and Flask-SeaSurf (a CSRF token on every POST, including logout).
- **Content Security Policy:** scripts and styles may only come from the
  app's own origin, and inline code is blocked. That is why the form script is
  a separate file.
- **Cookies:** the session cookie is HttpOnly, SameSite=Lax, and Secure on
  App Engine. `app.yaml` forces HTTPS for every URL.
- **Input:** names are checked on the server (letters, numbers, spaces,
  apostrophes, periods, and hyphens, 40 characters at most). Jinja escapes
  everything it renders, and request bodies are limited to 16 KB.
- **Local safety:** a local run refuses to start unless
  `DATASTORE_EMULATOR_HOST` is set, so development cannot write to the
  production database by accident.

### Hosting

App Engine standard environment, Python 3.12, F1 instances, scaling between
0 and 1 instance to stay within the free tier. The entrypoint runs gunicorn
with one worker (`-w 1`).

## Technology used

- Python 3.12, Flask 3.1, and Jinja templates
- Google App Engine standard environment
- Firestore in Datastore mode through `google-cloud-ndb`
- Google's Python 3 secure scaffold (`securescaffold`), which adds
  Flask-Talisman and Flask-SeaSurf
- Authlib for Google sign-in (OpenID Connect)
- gunicorn, python-dotenv, and requests
- HTML, CSS, and plain JavaScript
- pytest and the Datastore emulator for tests

## Project layout

```
main.py              App factory, routes, NDB middleware
settings.py          Flask settings loaded by the secure scaffold
app.yaml             App Engine configuration
data/ghosts.csv      Ghost name catalog
ghostpicker/
  auth.py            Google sign-in, login_required, safe redirects
  client.py          NDB client for App Engine or the emulator
  models.py          Datastore models
  names.py           Validating names, drawing and claiming ghost names
  seed.py            Loads the catalog into Datastore
  templates/         Jinja templates
  static/            CSS and the name form script
tests/               pytest suite, run against the emulator
```

## Running locally

You need:

- Python 3.12 or newer.
- The Google Cloud CLI with the Datastore emulator
  (`gcloud components install cloud-datastore-emulator`), which also needs
  Java.
- A Google OAuth client of type "Web application" with
  `http://localhost:8080/auth/callback` as an authorised redirect URI.

Steps:

1. Install the dependencies:

```
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt pytest
```

2. Copy `.env.example` to `.env`. Fill in `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, and a long random `SECRET_KEY`.

3. Start the emulator in a separate terminal:

```
gcloud beta emulators datastore start --host-port=localhost:8081 --project=ghost-name-picker --consistency=1.0
```

   `--consistency=1.0` matches production, where Datastore queries are
   strongly consistent. The emulator's default of 0.9 sometimes leaves a
   recent write out of query results, which makes some tests fail at random.

4. Run the app, then open http://localhost:8080:

```
python -m flask --app main run --port 8080
```

   The address you open must match the redirect URI exactly. Google treats
   `localhost` and `127.0.0.1` as different hosts.

## Tests

With the emulator running:

```
python -m pytest
```

Each test uses its own Datastore namespace, so tests do not share data. The
tests build the real app, which checks the Google client with Google at
startup, so they need network access and valid credentials in `.env`.

## Limitations and future improvements

- **Emails are public.** The brief asks for the holder's email next to each
  taken name, so anyone, signed in or not, can see every user's email. A real
  product would show it only to signed-in users, or mask it.
- **Stale emails.** If a user's Google email changes, their `User` record
  updates at the next sign-in, but the copy on their `Ghost` keeps the old
  address until they claim a new name. Updating both in `upsert_user` would
  fix this.
- **The catalog is loaded once.** Names added to `ghosts.csv` after the first
  load are ignored. Storing a catalog version, or adding an admin-only import
  page, would allow updates.
- **The startup check runs on every cold start.** The credential check calls
  Google from each worker whenever an instance starts. If Google cannot be
  reached at that moment, the instance fails to start. Running the check at
  deploy time instead would remove that dependency.
- **The tests need Google.** Because of the startup check, the test suite
  needs network access and real credentials. Stubbing the check in the tests
  would let anyone run them.
- **Offers are not reservations.** Two people can be shown the same name, and
  whoever chooses it second has to pick again. Holding offered names for a
  few minutes would avoid this.
- **Full scans.** The overview and each draw read every `Ghost`. That is fine
  for 43 names, but a large catalog would need paging, a query for unclaimed
  names, or a cache.
- **Secrets are injected at deploy time.** The committed `app.yaml` has an
  empty `env_variables` block. GitHub Actions appends `SECRET_KEY`,
  `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET` from GitHub Secrets before
  `gcloud app deploy`. Those values still live in the deployed App Engine
  configuration. Secret Manager would keep them out of that file.
- **No rate limiting** on drawing or claiming names.
- **Tests are not part of CI.** A push to `main` deploys through
  `.github/workflows/deploy.yaml`. That workflow does not run pytest or the
  Google style linters, so a failing test can still be deployed.

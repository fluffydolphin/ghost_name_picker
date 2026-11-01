"""Create the NDB client for App Engine or the local Datastore emulator."""

import os

from google.cloud import ndb


def create_ndb_client():
    """Return the NDB client for this process.

    On App Engine the client uses Cloud Datastore. Locally it uses the
    Datastore emulator, which requires DATASTORE_EMULATOR_HOST (for
    example ``localhost:8081``). A local process with that variable unset
    fails immediately instead of talking to production by accident.

    DATASTORE_NAMESPACE, when set, isolates one run from another. Tests
    set it. The running app leaves it empty and uses the default namespace.
    """
    on_app_engine = os.environ.get("GAE_ENV") == "standard"
    emulator = os.environ.get("DATASTORE_EMULATOR_HOST")
    if not on_app_engine and not emulator:
        raise RuntimeError(
            "Local runs need the Datastore emulator. "
            "Set DATASTORE_EMULATOR_HOST, for example localhost:8081."
        )

    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("DATASTORE_PROJECT_ID")
    )

    # Used by tests so test data doesn't get shared by other tests
    namespace = os.environ.get("DATASTORE_NAMESPACE") or None

    kwargs = {}
    if project:
        kwargs["project"] = project
    if namespace:
        kwargs["namespace"] = namespace
    return ndb.Client(**kwargs)

"""Load the checked-in ghost catalog into Datastore once."""

import csv
from pathlib import Path

from ghostpicker.models import CatalogState
from ghostpicker.models import Ghost

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "ghosts.csv"
_MARKER_ID = "ghosts"


def load_catalog(path=None):
    """Return (name, description) pairs from the catalog CSV.

    Args:
        path: Optional path. Defaults to data/ghosts.csv.

    Returns:
        A list of (name, description) tuples. Descriptions may be empty.
        Duplicate names keep the first row.
    """
    catalog_path = Path(path) if path else _CATALOG_PATH
    seen = set()
    rows = []
    with catalog_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for raw in reader:
            if not raw:
                continue
            name = raw[0].strip()
            if not name or name == "Ghost name":
                continue
            if name in seen:
                continue
            seen.add(name)
            description = raw[1].strip() if len(raw) > 1 else ""
            rows.append((name, description))
    return rows


def ensure_seeded(client):
    """Insert any catalog names that are not already stored.

    Existing entities are left alone, so a restart cannot wipe claims.
    The marker lives in Datastore, so a second app instance does not
    rely on memory in this process.

    Args:
        client: The NDB client for this process. Used only as a flag
            holder so later requests skip the marker read.
    """
    if getattr(client, "ghosts_seeded", False):
        return
    if CatalogState.get_by_id(_MARKER_ID) is None:
        for name, description in load_catalog():
            Ghost.get_or_insert(name, description=description)
        CatalogState(id=_MARKER_ID).put()
    client.ghosts_seeded = True

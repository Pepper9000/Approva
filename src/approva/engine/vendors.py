"""Vendor status lookup with conservative fuzzy matching."""

from difflib import get_close_matches

from approva import config, db


def vendor_status(name: str | None, db_path=None) -> str:
    """Return approved, unreviewed, blocked, or new for a vendor name."""
    if not name or not name.strip():
        return "new"
    with db.connection(db_path) as conn:
        vendors = [dict(row) for row in conn.execute("SELECT name,status FROM vendors")]
    by_normalized = {item["name"].casefold(): item["status"] for item in vendors}
    normalized = name.strip().casefold()
    if normalized in by_normalized:
        return by_normalized[normalized]
    matches = get_close_matches(normalized, by_normalized, n=1, cutoff=0.85)
    return by_normalized[matches[0]] if matches else "new"


def lookup_vendor_status(name: str | None, db_path=None) -> str:
    """Initialize reference data if needed, then look up a vendor status."""
    if not config.database_path().exists() and db_path is None:
        db.seed_from_yaml()
    return vendor_status(name, db_path)
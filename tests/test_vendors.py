from approva import db
from approva.engine.vendors import vendor_status


def test_vendor_status_exact_case_insensitive_and_unknown(tmp_path):
    path = tmp_path / "approva.db"
    db.seed_from_yaml(db_path=path)
    assert vendor_status("Figma", path) == "approved"
    assert vendor_status("fIgMa", path) == "approved"
    assert vendor_status("VoxLens AI", path) == "new"


def test_vendor_status_uses_fuzzy_match(tmp_path):
    path = tmp_path / "approva.db"
    db.seed_from_yaml(db_path=path)
    assert vendor_status("Figm", path) == "approved"
from approva import db


def test_seed_request_persistence_and_sequential_ids(tmp_path):
    path = tmp_path / "approva.db"
    db.seed_from_yaml(db_path=path)

    with db.connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 11

    db.save_request("REQ-0001", path, requester_id="E001", status="RECEIVED")
    assert db.get_request("REQ-0001", path)["requester_id"] == "E001"
    assert db.get_approvals("REQ-0001", path) == []
    assert db.next_id("TKT", path) == "TKT-0001"
    assert db.next_id("TKT", path) == "TKT-0002"


def test_init_db_adds_laya_column_to_an_existing_requests_table(tmp_path):
    path = tmp_path / "older-schema.db"
    with db.connection(path) as conn:
        conn.execute("CREATE TABLE requests(id TEXT PRIMARY KEY, status TEXT)")

    db.init_db(path)

    with db.connection(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
    assert "laya_json" in columns
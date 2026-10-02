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
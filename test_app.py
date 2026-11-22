"""Flask route tests (need Flask + pytest installed)."""
import app as appmod


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_FILE", tmp_path / "records.txt")
    monkeypatch.setattr(appmod, "SETTINGS_FILE", tmp_path / "settings.json")
    c = appmod.app.test_client()
    html = c.get("/").get_data(as_text=True)
    token = html.split('name="csrf-token" content="')[1].split('"')[0]
    return c, {"X-CSRF-Token": token}


def add_sample(c, h):
    for m, v in [("2026-01", 150), ("2026-02", 200), ("2026-03", 180)]:
        assert c.post("/api/records", json={"month": m, "kwh": v}, headers=h).status_code == 201


def test_sample_results(tmp_path, monkeypatch):
    c, h = client(tmp_path, monkeypatch)
    add_sample(c, h)
    s = c.get("/api/records").get_json()["summary"]
    assert s["total"] == 530
    assert s["average"] == 176.67
    assert s["highest"]["label"] == "February 2026"
    assert s["lowest"]["label"] == "January 2026"
    assert s["forecast"]["value"] == 176.67 and s["forecast"]["label"] == "April 2026"


def test_csrf_and_validation(tmp_path, monkeypatch):
    c, h = client(tmp_path, monkeypatch)
    assert c.post("/api/records", json={"month": "2026-01", "kwh": 5}).status_code == 403
    for bad in [{"month": "2026-13", "kwh": 5}, {"month": "x", "kwh": 5},
                {"month": "2026-01", "kwh": -1}, {"month": "2026-01", "kwh": "abc"},
                {"month": "2026-01", "kwh": "nan"}]:
        assert c.post("/api/records", json=bad, headers=h).status_code == 400


def test_update_delete_and_clear(tmp_path, monkeypatch):
    c, h = client(tmp_path, monkeypatch)
    c.post("/api/records", json={"month": "2026-01", "kwh": 10}, headers=h)
    c.post("/api/records", json={"month": "2026-01", "kwh": 20}, headers=h)
    assert len(c.get("/api/records").get_json()["records"]) == 1
    assert c.delete("/api/records/2026-01", headers=h).get_json()["summary"]["count"] == 0
    add_sample(c, h)
    assert c.delete("/api/records", headers=h).get_json()["summary"]["count"] == 0


def test_settings(tmp_path, monkeypatch):
    c, h = client(tmp_path, monkeypatch)
    add_sample(c, h)
    r = c.post("/api/settings", json={"rate": 2, "budget": 300, "method": "trend"}, headers=h)
    d = r.get_json()
    assert r.status_code == 200 and d["settings"]["method"] == "trend"
    assert d["summary"]["cost"] is not None
    assert c.post("/api/settings", json={"method": "magic"}, headers=h).status_code == 400
    assert c.post("/api/settings", json={"rate": -5}, headers=h).status_code == 400


def test_import_export(tmp_path, monkeypatch):
    c, h = client(tmp_path, monkeypatch)
    csv = "month,kwh\n2026-01,150\nFeb 2026,200\nbroken\n"
    r = c.post("/api/import", json={"csv": csv}, headers=h)
    d = r.get_json()
    assert r.status_code == 201 and d["imported"]["added"] == 2 and d["imported"]["skipped"] == 1
    assert c.post("/api/import", json={"csv": "garbage"}, headers=h).status_code == 400
    out = c.get("/export.csv").get_data(as_text=True)
    assert out.splitlines() == ["month,kwh", "2026-01,150.00", "2026-02,200.00"]


def test_security_headers(tmp_path, monkeypatch):
    c, _ = client(tmp_path, monkeypatch)
    r = c.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"

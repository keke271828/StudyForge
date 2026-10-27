import sqlite3

from fastapi.testclient import TestClient

from studyforge.config import data_dir
from studyforge.db import create_project, one
from studyforge.server import app


def test_categories_move_sources_and_keep_sources_when_category_deleted():
    client = TestClient(app)
    project = create_project("物理")
    other = create_project("编程")
    mechanics = client.post(f"/api/projects/{project['id']}/categories", json={"name": "经典力学"})
    assert mechanics.status_code == 200
    category_id = mechanics.json()["id"]
    assert client.post(f"/api/projects/{project['id']}/categories", json={"name": "经典力学"}).status_code == 409
    response = client.post("/api/import/file", data={"project_id": project["id"], "category_id": category_id},
                           files={"file": ("lecture.txt", "F = ma".encode())})
    assert response.status_code == 200
    source_id = response.json()["source_id"]
    listed = client.get(f"/api/projects/{project['id']}/sources").json()
    assert listed[0]["category_id"] == category_id
    assert client.get(f"/api/projects/{project['id']}/categories").json()[0]["source_count"] == 1
    foreign = client.post(f"/api/projects/{other['id']}/categories", json={"name": "算法"}).json()["id"]
    assert client.put(f"/api/sources/{source_id}/category", json={"category_id": foreign}).status_code == 400
    assert client.put(f"/api/sources/{source_id}/category", json={"category_id": None}).status_code == 200
    assert client.put(f"/api/sources/{source_id}/category", json={"category_id": category_id}).status_code == 200
    assert client.put(f"/api/categories/{category_id}", json={"name": "力学基础"}).json()["name"] == "力学基础"
    assert client.delete(f"/api/categories/{category_id}").status_code == 200
    assert one("SELECT category_id FROM sources WHERE id=?", (source_id,))["category_id"] is None


def test_existing_database_sources_migrate_to_uncategorized():
    path = data_dir() / "studyforge.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,created_at TEXT);
        CREATE TABLE sources(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,kind TEXT,
          original_path TEXT,segments_json TEXT,status TEXT,error TEXT,created_at TEXT);
        INSERT INTO projects VALUES('old-project','原项目','2026-01-01');
        INSERT INTO sources VALUES('old-source','old-project','旧资料','txt','old.txt','[]','ready',NULL,'2026-01-01');
    """)
    connection.commit()
    connection.close()
    assert one("SELECT category_id FROM sources WHERE id=?", ("old-source",)) == {"category_id": None}
    client = TestClient(app)
    category = client.post("/api/projects/old-project/categories", json={"name": "旧资料分类"}).json()
    assert client.put("/api/sources/old-source/category", json={"category_id": category["id"]}).status_code == 200

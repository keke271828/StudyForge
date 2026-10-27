import pytest


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDYFORGE_SEMANTIC_MODEL_DIR", str(tmp_path / "isolated-model"))

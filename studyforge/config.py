from __future__ import annotations

import os
import hashlib
from pathlib import Path


def data_dir() -> Path:
    root = os.environ.get("STUDYFORGE_DATA_DIR")
    path = Path(root) if root else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "StudyForge"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def files_dir() -> Path:
    path = data_dir() / "files"
    path.mkdir(exist_ok=True)
    return path


def artifacts_dir() -> Path:
    path = data_dir() / "artifacts"
    path.mkdir(exist_ok=True)
    return path


def temp_dir() -> Path:
    path = data_dir() / "tmp"
    path.mkdir(exist_ok=True)
    return path


def derived_dir(source: Path, kind: str) -> Path:
    """Keep extracted media tied to one original and its current revision."""
    source = source.resolve()
    stat = source.stat()
    identity = f'{source}\0{stat.st_size}\0{stat.st_mtime_ns}'
    token = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    folder = temp_dir() / f'{kind}-{token}'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import keyring
        return keyring.get_password("StudyForge", name)
    except Exception:
        return None


def set_secret(name: str, value: str) -> None:
    import keyring
    keyring.set_password("StudyForge", name, value)


def delete_secret(name: str) -> None:
    import keyring
    try: keyring.delete_password('StudyForge', name)
    except keyring.errors.PasswordDeleteError: pass

"""Shared pytest fixtures for isolated DB and media storage per test."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import set_data_dir
from app.main import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a FastAPI TestClient wired to an isolated temporary data directory."""
    monkeypatch.setenv("LITETUBE_SKIP_SEED", "1")
    monkeypatch.setenv("LITETUBE_SECRET_KEY", "test-secret-key-for-pytest-only")
    set_data_dir(tmp_path)

    with TestClient(app) as test_client:
        yield test_client


def make_png_bytes(color: tuple[int, int, int] = (40, 120, 220)) -> bytes:
    """Create a valid in-memory PNG thumbnail image."""
    buf = BytesIO()
    Image.new("RGB", (160, 90), color).save(buf, format="PNG")
    return buf.getvalue()

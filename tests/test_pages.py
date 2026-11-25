"""Tests for HTML pages, static assets, and real WebM frame thumbnail extraction."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import settings


def test_html_pages_and_static_assets(client: TestClient) -> None:
    for path in ("/", "/upload", "/watch/nonexistent"):
        res = client.get(path)
        assert res.status_code == 200
        assert "LiteTube" in res.text

    for asset in (
        "/static/css/styles.css",
        "/static/js/api.js",
        "/static/js/auth_ui.js",
        "/static/js/home.js",
        "/static/js/watch.js",
        "/static/js/upload.js",
    ):
        res = client.get(asset)
        assert res.status_code == 200
        assert len(res.text) > 50


def test_real_webm_upload_extracts_frame_thumbnail(
    client: TestClient, tmp_path: Path
) -> None:
    # Build a small real VP8 WebM file on disk using OpenCV
    clip_path = tmp_path / "real_clip.webm"
    writer = cv2.VideoWriter(
        str(clip_path), cv2.VideoWriter_fourcc(*"VP80"), 24, (320, 180)
    )
    for _ in range(12):
        frame = np.full((180, 320, 3), (20, 160, 240), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    webm_bytes = clip_path.read_bytes()

    reg = client.post(
        "/api/auth/register",
        json={"username": "opencv_uploader", "password": "password123"},
    )
    assert reg.status_code == 201

    up = client.post(
        "/api/videos",
        data={
            "title": "Real OpenCV Clip",
            "category": "Tech",
            "tags": "#python, #webm",
            "duration_seconds": "1",
        },
        files={"video": ("real_clip.webm", webm_bytes, "video/webm")},
    )
    assert up.status_code == 201
    video = up.json()["video"]
    assert video["tags"] == ["python", "webm"]

    thumb_path = settings.thumbnails_dir / f"{video['id']}.png"
    assert thumb_path.is_file()
    assert thumb_path.stat().st_size > 200

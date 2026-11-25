"""Video upload, search, filtering, view tracking, deletion, and seeder tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import set_data_dir, settings
from app.main import app
from tests.conftest import make_png_bytes

WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 128
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128


def _register_user(client: TestClient, username: str) -> int:
    res = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert res.status_code == 201
    return int(res.json()["user"]["id"])


def test_upload_requires_auth(client: TestClient) -> None:
    res = client.post(
        "/api/videos",
        data={"title": "Guest attempt", "category": "Tech"},
        files={"video": ("clip.webm", WEBM_BYTES, "video/webm")},
    )
    assert res.status_code == 401


def test_upload_search_filter_views_and_owner_delete(client: TestClient) -> None:
    _register_user(client, "creator_one")

    # Reject non-video upload or spoofed magic bytes
    bad_ext = client.post(
        "/api/videos",
        data={"title": "Not a video", "category": "Tech"},
        files={"video": ("notes.txt", b"hello world", "text/plain")},
    )
    assert bad_ext.status_code == 400

    spoofed_mp4 = client.post(
        "/api/videos",
        data={"title": "Fake MP4", "category": "Tech"},
        files={"video": ("fake.mp4", b"not really an mp4 container", "video/mp4")},
    )
    assert spoofed_mp4.status_code == 400

    # Upload valid WebM with fallback thumbnail
    up1 = client.post(
        "/api/videos",
        data={
            "title": "FastAPI Range Demo",
            "description": "Streaming tutorial",
            "category": "Tech",
            "tags": "python,fastapi",
            "duration_seconds": "5",
        },
        files={"video": ("demo.webm", WEBM_BYTES, "video/webm")},
    )
    assert up1.status_code == 201
    vid1 = up1.json()["video"]
    assert vid1["video_mime"] == "video/webm"
    assert vid1["tags"] == ["python", "fastapi"]
    assert (settings.videos_dir / f"{vid1['id']}.webm").is_file()
    assert (settings.thumbnails_dir / f"{vid1['id']}.png").is_file()

    # Upload valid MP4 with custom thumbnail
    up2 = client.post(
        "/api/videos",
        data={
            "title": "Chill Synth Beat",
            "description": "Ambient loop",
            "category": "Music",
            "tags": "synth,ambient",
            "duration_seconds": "12",
        },
        files={
            "video": ("beat.mp4", MP4_BYTES, "video/mp4"),
            "thumbnail": ("cover.png", make_png_bytes(), "image/png"),
        },
    )
    assert up2.status_code == 201
    vid2 = up2.json()["video"]

    # Record views on vid2 so sort=views puts it first
    view_res = client.post(f"/api/videos/{vid2['id']}/view")
    assert view_res.status_code == 200
    assert view_res.json()["views"] == 1

    # Search, category, channel, and sort queries
    search_res = client.get("/api/videos", params={"q": "FastAPI"})
    assert search_res.status_code == 200
    assert [v["id"] for v in search_res.json()["videos"]] == [vid1["id"]]

    cat_res = client.get("/api/videos", params={"category": "Music"})
    assert [v["id"] for v in cat_res.json()["videos"]] == [vid2["id"]]

    views_res = client.get("/api/videos", params={"sort": "views"})
    assert [v["id"] for v in views_res.json()["videos"]] == [vid2["id"], vid1["id"]]

    # Watch details + related videos excludes self
    detail = client.get(f"/api/videos/{vid1['id']}")
    assert detail.status_code == 200
    assert [r["id"] for r in detail.json()["related"]] == [vid2["id"]]

    # Another user cannot delete creator_one's video
    client.post("/api/auth/logout")
    _register_user(client, "other_user")
    forbidden = client.delete(f"/api/videos/{vid1['id']}")
    assert forbidden.status_code == 403

    # Owner can delete and cleans up disk artifacts
    client.post(
        "/api/auth/login",
        json={"username": "creator_one", "password": "password123"},
    )
    deleted = client.delete(f"/api/videos/{vid1['id']}")
    assert deleted.status_code == 200
    assert not (settings.videos_dir / f"{vid1['id']}.webm").exists()
    assert not (settings.thumbnails_dir / f"{vid1['id']}.png").exists()
    assert client.get(f"/api/videos/{vid1['id']}").status_code == 404


def test_seed_generates_playable_clips_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LITETUBE_SKIP_SEED", "0")
    monkeypatch.setenv("LITETUBE_SECRET_KEY", "seed-test-secret")
    set_data_dir(tmp_path)

    with TestClient(app) as seeded_client:
        feed = seeded_client.get("/api/videos")
        assert feed.status_code == 200
        videos = feed.json()["videos"]
        assert len(videos) == 6
        for v in videos:
            assert v["file_size"] > 1000
            thumb_res = seeded_client.get(v["thumbnail_url"])
            assert thumb_res.status_code == 200
            assert thumb_res.headers["content-type"].startswith("image/")

    # Re-entering lifespan does not duplicate seed records
    with TestClient(app) as second_boot:
        assert second_boot.get("/api/videos").json()["total"] == 6

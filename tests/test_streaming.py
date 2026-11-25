"""HTTP 206 byte-range video streaming, DB persistence, and thumbnail security tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from tests.conftest import make_png_bytes

SAMPLE_PAYLOAD = b"\x1a\x45\xdf\xa3" + b"0123456789ABCDEF" * 10  # 164 bytes


def _upload_sample(
    client: TestClient,
    username: str = "streamer",
    payload: bytes = SAMPLE_PAYLOAD,
    with_custom_thumb: bool = False,
) -> tuple[str, str, str]:
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    files: dict[str, tuple[str, bytes, str]] = {
        "video": ("range.webm", payload, "video/webm")
    }
    if with_custom_thumb:
        files["thumbnail"] = ("cover.png", make_png_bytes(), "image/png")

    res = client.post(
        "/api/videos",
        data={"title": "Range Test Clip", "category": "Tech"},
        files=files,
    )
    assert res.status_code == 201
    vid = res.json()["video"]
    return vid["id"], vid["stream_url"], vid["thumbnail_url"]


def test_http_range_streaming_and_bounds(client: TestClient) -> None:
    _vid_id, stream_url, thumb_url = _upload_sample(client)
    total = len(SAMPLE_PAYLOAD)

    # Full GET 200
    full = client.get(stream_url)
    assert full.status_code == 200
    assert full.headers.get("accept-ranges") == "bytes"
    assert full.headers.get("content-length") == str(total)
    assert full.content == SAMPLE_PAYLOAD

    # HEAD probe
    head = client.head(stream_url)
    assert head.status_code == 200
    assert head.headers.get("content-length") == str(total)

    # Partial range 0-9 -> 206
    part = client.get(stream_url, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206
    assert part.headers.get("content-range") == f"bytes 0-9/{total}"
    assert part.headers.get("content-length") == "10"
    assert part.content == SAMPLE_PAYLOAD[:10]

    # Open-ended range 150- -> 206
    tail_open = client.get(stream_url, headers={"Range": "bytes=150-"})
    assert tail_open.status_code == 206
    assert tail_open.headers.get("content-range") == f"bytes 150-{total - 1}/{total}"
    assert tail_open.content == SAMPLE_PAYLOAD[150:]

    # Suffix range -6 -> 206
    suffix = client.get(stream_url, headers={"Range": "bytes=-6"})
    assert suffix.status_code == 206
    assert suffix.headers.get("content-range") == f"bytes {total - 6}-{total - 1}/{total}"
    assert suffix.content == SAMPLE_PAYLOAD[-6:]

    # Out-of-bounds range -> 416
    oob = client.get(stream_url, headers={"Range": f"bytes={total + 50}-{total + 100}"})
    assert oob.status_code == 416
    assert oob.headers.get("content-range") == f"bytes */{total}"

    # Valid thumbnail returns 200, invalid/traversal returns 404
    assert client.get(thumb_url).status_code == 200
    assert client.get("/media/thumbnails/../../app.db").status_code == 404


def test_video_and_thumbnail_survive_ephemeral_disk_wipe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force small 48-byte DB chunks to exercise multi-chunk boundary slicing
    monkeypatch.setattr("app.routes.video_routes.DB_CHUNK_SIZE", 48)
    monkeypatch.setattr("app.routes.media_routes.STREAM_CHUNK_SIZE", 32)

    payload = b"\x1a\x45\xdf\xa3" + bytes(range(256))[:170]
    vid_id, stream_url, thumb_url = _upload_sample(
        client, username="redeploy_tester", payload=payload, with_custom_thumb=True
    )

    # Simulate container restart/redeploy: wipe local ephemeral video & thumbnail files
    video_file = settings.videos_dir / f"{vid_id}.webm"
    thumb_file = settings.thumbnails_dir / f"{vid_id}.png"
    assert video_file.is_file()
    assert thumb_file.is_file()
    video_file.unlink()
    thumb_file.unlink()

    # Full GET streams seamlessly from database chunks
    full = client.get(stream_url)
    assert full.status_code == 200
    assert full.content == payload

    # Cross-chunk HTTP 206 Range request (spans chunks 0, 1, and 2)
    part = client.get(stream_url, headers={"Range": "bytes=40-115"})
    assert part.status_code == 206
    assert part.headers.get("content-range") == f"bytes 40-115/{len(payload)}"
    assert part.content == payload[40:116]

    # Suffix range and HEAD still work without disk files
    suffix = client.get(stream_url, headers={"Range": "bytes=-15"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-15:]
    assert client.head(stream_url).status_code == 200

    # Thumbnail still serves cleanly from database BLOB
    thumb_res = client.get(thumb_url)
    assert thumb_res.status_code == 200
    assert thumb_res.headers["content-type"].startswith("image/png")
    assert len(thumb_res.content) > 100

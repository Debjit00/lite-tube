"""HTTP 206 byte-range video streaming and thumbnail security tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

SAMPLE_PAYLOAD = b"\x1a\x45\xdf\xa3" + b"0123456789ABCDEF" * 10  # 164 bytes


def _upload_sample(client: TestClient) -> tuple[str, str]:
    client.post(
        "/api/auth/register",
        json={"username": "streamer", "password": "password123"},
    )
    res = client.post(
        "/api/videos",
        data={"title": "Range Test Clip", "category": "Tech"},
        files={"video": ("range.webm", SAMPLE_PAYLOAD, "video/webm")},
    )
    assert res.status_code == 201
    vid = res.json()["video"]
    return vid["stream_url"], vid["thumbnail_url"]


def test_http_range_streaming_and_bounds(client: TestClient) -> None:
    stream_url, thumb_url = _upload_sample(client)
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

"""HTTP 206 byte-range video streaming and safe thumbnail serving routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from app.config import STREAM_CHUNK_SIZE, settings
from app.db import db_session

router = APIRouter(prefix="/media", tags=["media"])

SAFE_THUMBNAIL_RE = re.compile(r"^[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp)$")


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse an HTTP Range header ('bytes=start-end') against file_size."""
    if file_size <= 0 or not range_header.startswith("bytes="):
        return None

    spec = range_header[6:].strip()
    if "," in spec or "-" not in spec:
        return None

    start_str, end_str = spec.split("-", 1)
    start_str = start_str.strip()
    end_str = end_str.strip()

    try:
        if start_str == "":
            if not end_str:
                return None
            suffix_len = int(end_str)
            if suffix_len <= 0:
                return None
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
    except ValueError:
        return None

    if start < 0 or start >= file_size or end < start:
        return None

    return start, min(end, file_size - 1)


def _iter_file_range(
    file_path: Path, start: int, end: int, chunk_size: int = STREAM_CHUNK_SIZE
) -> Iterator[bytes]:
    remaining = end - start + 1
    with file_path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _resolve_safe_path(base_dir: Path, filename: str) -> Path:
    base_resolved = base_dir.resolve()
    target = (base_resolved / filename).resolve()
    if not target.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found."
        )
    return target


@router.api_route("/videos/{video_id}", methods=["GET", "HEAD"])
def stream_video(video_id: str, request: Request) -> Response:
    """Stream a stored video with full HTTP 206 Partial Content Range support."""
    with db_session() as db:
        row = db.execute(
            "SELECT video_filename, video_mime FROM videos WHERE id = %s",
            (video_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found."
        )

    file_path = _resolve_safe_path(settings.videos_dir, row["video_filename"])
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video file missing."
        )

    file_size = file_path.stat().st_size
    media_type = row["video_mime"]
    range_header = request.headers.get("range")

    if range_header:
        parsed = parse_range_header(range_header, file_size)
        if parsed is None:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={
                    "Content-Range": f"bytes */{file_size}",
                    "Accept-Ranges": "bytes",
                },
            )
        start, end = parsed
        content_length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Cache-Control": "public, max-age=3600",
        }
        if request.method == "HEAD":
            return Response(
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                headers=headers,
                media_type=media_type,
            )
        return StreamingResponse(
            _iter_file_range(file_path, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
            media_type=media_type,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "public, max-age=3600",
    }
    if request.method == "HEAD" or file_size == 0:
        return Response(
            status_code=status.HTTP_200_OK,
            headers=headers,
            media_type=media_type,
        )
    return StreamingResponse(
        _iter_file_range(file_path, 0, file_size - 1),
        status_code=status.HTTP_200_OK,
        headers=headers,
        media_type=media_type,
    )


@router.get("/thumbnails/{filename}")
def get_thumbnail(filename: str) -> FileResponse:
    """Serve a validated thumbnail image from local storage."""
    if not SAFE_THUMBNAIL_RE.match(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found."
        )
    file_path = _resolve_safe_path(settings.thumbnails_dir, filename)
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found."
        )
    return FileResponse(
        file_path,
        headers={"Cache-Control": "public, max-age=3600"},
    )

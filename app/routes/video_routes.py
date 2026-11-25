"""Video discovery, upload, view tracking, and management API endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.auth import require_current_user
from app.config import (
    ALLOWED_THUMBNAIL_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    CATEGORIES,
    DB_CHUNK_SIZE,
    MAX_THUMBNAIL_BYTES,
    MAX_VIDEO_BYTES,
    UPLOAD_CHUNK_SIZE,
    ensure_directories,
    settings,
)
from app.db import db_session, store_video_chunks

router = APIRouter(prefix="/api", tags=["videos"])

VIDEO_SELECT = """
SELECT
    v.id,
    v.user_id,
    v.title,
    v.description,
    v.category,
    v.tags,
    v.video_filename,
    v.video_mime,
    v.file_size,
    v.duration_seconds,
    v.thumbnail_filename,
    v.views,
    v.created_at,
    u.username AS channel_username,
    u.display_name AS channel_display_name,
    u.avatar_color AS channel_avatar_color
FROM videos v
JOIN users u ON u.id = v.user_id
"""


def serialize_video(row: Any) -> dict[str, Any]:
    """Convert a joined video+user database row into the API response shape."""
    raw_tags = row["tags"] or ""
    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "tags": tags,
        "duration_seconds": row["duration_seconds"],
        "views": row["views"],
        "file_size": row["file_size"],
        "video_mime": row["video_mime"],
        "created_at": row["created_at"],
        "stream_url": f"/media/videos/{row['id']}",
        "thumbnail_url": f"/media/thumbnails/{row['thumbnail_filename']}",
        "channel": {
            "id": row["user_id"],
            "username": row["channel_username"],
            "display_name": row["channel_display_name"],
            "avatar_color": row["channel_avatar_color"],
        },
    }


def _escape_like(term: str) -> str:
    return term.replace("|", "||").replace("%", "|%").replace("_", "|_")


def _is_valid_video_magic(header: bytes, ext: str) -> bool:
    if ext == ".mp4":
        return len(header) >= 12 and b"ftyp" in header[:16]
    if ext == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    return False


async def _save_uploaded_video(
    upload: UploadFile, video_id: str
) -> tuple[str, str, int, Path]:
    ensure_directories()
    orig_name = upload.filename or ""
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .mp4 and .webm video files are supported.",
        )

    expected_mime = ALLOWED_VIDEO_EXTENSIONS[ext]
    temp_path = settings.videos_dir / f".tmp_{video_id}_{secrets.token_hex(4)}{ext}"
    final_filename = f"{video_id}{ext}"
    final_path = settings.videos_dir / final_filename

    total_size = 0
    header_bytes = bytearray()

    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_VIDEO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video exceeds maximum allowed size ({MAX_VIDEO_BYTES // (1024 * 1024)} MB).",
                    )
                if len(header_bytes) < 32:
                    needed = 32 - len(header_bytes)
                    header_bytes.extend(chunk[:needed])
                out.write(chunk)

        if total_size == 0 or not _is_valid_video_magic(bytes(header_bytes), ext):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty or does not match a valid MP4/WebM container.",
            )

        temp_path.replace(final_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return final_filename, expected_mime, total_size, final_path


def render_fallback_thumbnail(
    target_path: Path, title: str, category: str
) -> None:
    """Render a clean 16:9 dark fallback thumbnail PNG using Pillow."""
    width, height = 640, 360
    img = Image.new("RGB", (width, height), (18, 22, 32))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(18 + ratio * 24)
        g = int(22 + ratio * 18)
        b = int(38 + ratio * 46)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    draw.rounded_rectangle([(32, 32), (160, 68)], radius=16, fill=(220, 38, 38))
    font = ImageFont.load_default()
    draw.text((48, 44), category.upper()[:12], fill=(255, 255, 255), font=font)

    snippet = title.strip()[:46] or "Uploaded Video"
    draw.text((36, 168), snippet, fill=(241, 241, 241), font=font)
    draw.ellipse([(290, 230), (350, 290)], fill=(255, 255, 255))
    draw.polygon([(312, 245), (312, 275), (338, 260)], fill=(18, 22, 32))
    img.save(target_path, format="PNG")


def _extract_first_frame_thumbnail(video_path: Path, target_path: Path) -> bool:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        if not ok or frame is None:
            return False
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((640, 360), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (640, 360), (15, 15, 15))
        offset_x = (640 - img.width) // 2
        offset_y = (360 - img.height) // 2
        canvas.paste(img, (offset_x, offset_y))
        canvas.save(target_path, format="PNG")
        return True
    except Exception:
        return False
    finally:
        cap.release()


async def _save_or_generate_thumbnail(
    thumb_upload: UploadFile | None,
    video_id: str,
    title: str,
    category: str,
    video_path: Path,
) -> tuple[str, bytes]:
    ensure_directories()
    thumb_filename = f"{video_id}.png"
    thumb_path = settings.thumbnails_dir / thumb_filename

    if thumb_upload is not None and (thumb_upload.filename or "").strip():
        ext = Path(thumb_upload.filename or "").suffix.lower()
        if ext not in ALLOWED_THUMBNAIL_EXTENSIONS:
            await thumb_upload.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Thumbnail must be a PNG, JPEG, or WebP image.",
            )
        raw_bytes = await thumb_upload.read(MAX_THUMBNAIL_BYTES + 1)
        await thumb_upload.close()
        if not raw_bytes or len(raw_bytes) > MAX_THUMBNAIL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Thumbnail must be non-empty and under 5 MB.",
            )
        try:
            with Image.open(BytesIO(raw_bytes)) as verified:
                verified.verify()
            with Image.open(BytesIO(raw_bytes)) as img:
                rgb = img.convert("RGB")
                rgb.thumbnail((1280, 720), Image.Resampling.LANCZOS)
                rgb.save(thumb_path, format="PNG", optimize=True)
            return thumb_filename, thumb_path.read_bytes()
        except (UnidentifiedImageError, OSError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or corrupted thumbnail image.",
            )

    if not _extract_first_frame_thumbnail(video_path, thumb_path):
        render_fallback_thumbnail(thumb_path, title, category)

    return thumb_filename, thumb_path.read_bytes()


@router.get("/categories")
def list_categories() -> dict[str, list[str]]:
    """Return available feed categories."""
    return {"categories": ["All", *CATEGORIES]}


@router.get("/videos")
def list_videos(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="All", max_length=40),
    channel: str = Query(default="", max_length=40),
    sort: str = Query(default="newest"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List videos with search, category/channel filtering, and sorting."""
    where_clauses: list[str] = []
    params: list[Any] = []

    search = q.strip()
    if search:
        pattern = f"%{_escape_like(search)}%"
        where_clauses.append(
            """(
                v.title LIKE %s ESCAPE '|'
                OR v.description LIKE %s ESCAPE '|'
                OR v.tags LIKE %s ESCAPE '|'
                OR u.display_name LIKE %s ESCAPE '|'
                OR u.username LIKE %s ESCAPE '|'
            )"""
        )
        params.extend([pattern, pattern, pattern, pattern, pattern])

    cat = category.strip()
    if cat and cat.lower() != "all":
        where_clauses.append("LOWER(v.category) = LOWER(%s)")
        params.append(cat)

    chan = channel.strip()
    if chan:
        where_clauses.append("u.username = %s")
        params.append(chan)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = (
        "ORDER BY v.views DESC, v.created_at DESC, v.id DESC"
        if sort == "views"
        else "ORDER BY v.created_at DESC, v.id DESC"
    )

    with db_session() as db:
        total_row = db.execute(
            f"SELECT COUNT(*) AS cnt FROM videos v JOIN users u ON u.id = v.user_id {where_sql}",
            params,
        ).fetchone()
        rows = db.execute(
            f"{VIDEO_SELECT} {where_sql} {order_sql} LIMIT %s OFFSET %s",
            [*params, limit, offset],
        ).fetchall()

    return {
        "videos": [serialize_video(row) for row in rows],
        "total": total_row["cnt"] if total_row else 0,
    }


@router.get("/videos/{video_id}")
def get_video(video_id: str) -> dict[str, Any]:
    """Fetch single video details alongside ranked 'Up Next' related videos."""
    with db_session() as db:
        row = db.execute(f"{VIDEO_SELECT} WHERE v.id = %s", (video_id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video not found."
            )

        related_rows = db.execute(
            f"""
            {VIDEO_SELECT}
            WHERE v.id != %s
            ORDER BY
                CASE WHEN v.category = %s THEN 0 ELSE 1 END,
                v.views DESC,
                v.created_at DESC
            LIMIT 10
            """,
            (video_id, row["category"]),
        ).fetchall()

    return {
        "video": serialize_video(row),
        "related": [serialize_video(r) for r in related_rows],
    }


def _persist_uploaded_video_record(
    *,
    video_id: str,
    user_id: int,
    title: str,
    description: str,
    category: str,
    tags: str,
    video_filename: str,
    video_mime: str,
    file_size: int,
    duration_seconds: int,
    thumb_filename: str,
    thumb_bytes: bytes,
    video_path: Path,
    chunk_size: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO videos (
                id, user_id, title, description, category, tags,
                video_filename, video_mime, file_size, duration_seconds,
                thumbnail_filename, thumbnail_data, chunk_size, views, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
            """,
            (
                video_id,
                user_id,
                title,
                description,
                category,
                tags,
                video_filename,
                video_mime,
                file_size,
                duration_seconds,
                thumb_filename,
                thumb_bytes,
                chunk_size,
                now,
            ),
        )
        store_video_chunks(db, video_id, video_path, chunk_size)
        row = db.execute(f"{VIDEO_SELECT} WHERE v.id = %s", (video_id,)).fetchone()
    return serialize_video(row)


@router.post("/videos", status_code=status.HTTP_201_CREATED)
async def upload_video(
    title: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default="General"),
    tags: str = Form(default=""),
    duration_seconds: int = Form(default=0),
    video: UploadFile = File(...),
    thumbnail: UploadFile | None = File(default=None),
    current_user: dict[str, Any] = Depends(require_current_user),
) -> dict[str, Any]:
    """Upload a video and metadata (requires authenticated user)."""
    clean_title = title.strip()
    if not clean_title or len(clean_title) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title is required and must be at most 120 characters.",
        )

    clean_desc = description.strip()[:5000]
    clean_category = category.strip() or "General"
    if clean_category not in CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category must be one of: {', '.join(CATEGORIES)}.",
        )

    normalized_tags = ",".join(
        [
            t.strip().lstrip("#").lower()[:24]
            for t in tags.split(",")
            if t.strip().lstrip("#")
        ][:10]
    )
    safe_duration = max(0, min(int(duration_seconds), 86400))

    video_id = secrets.token_urlsafe(8)
    video_filename, video_mime, file_size, video_path = await _save_uploaded_video(
        video, video_id
    )

    thumb_filename = ""
    try:
        thumb_filename, thumb_bytes = await _save_or_generate_thumbnail(
            thumbnail, video_id, clean_title, clean_category, video_path
        )
        serialized = await run_in_threadpool(
            _persist_uploaded_video_record,
            video_id=video_id,
            user_id=current_user["id"],
            title=clean_title,
            description=clean_desc,
            category=clean_category,
            tags=normalized_tags,
            video_filename=video_filename,
            video_mime=video_mime,
            file_size=file_size,
            duration_seconds=safe_duration,
            thumb_filename=thumb_filename,
            thumb_bytes=thumb_bytes,
            video_path=video_path,
            chunk_size=DB_CHUNK_SIZE,
        )
    except Exception:
        video_path.unlink(missing_ok=True)
        if thumb_filename:
            (settings.thumbnails_dir / thumb_filename).unlink(missing_ok=True)
        raise

    return {"video": serialized}


@router.post("/videos/{video_id}/view")
def record_view(video_id: str) -> dict[str, int]:
    """Increment a video's view counter by 1."""
    with db_session() as db:
        cursor = db.execute(
            "UPDATE videos SET views = views + 1 WHERE id = %s",
            (video_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video not found."
            )
        row = db.execute(
            "SELECT views FROM videos WHERE id = %s", (video_id,)
        ).fetchone()
    return {"views": row["views"]}


@router.delete("/videos/{video_id}")
def delete_video(
    video_id: str,
    current_user: dict[str, Any] = Depends(require_current_user),
) -> dict[str, Any]:
    """Delete a video owned by the current authenticated user."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, user_id, video_filename, thumbnail_filename FROM videos WHERE id = %s",
            (video_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video not found."
            )
        if row["user_id"] != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete videos uploaded by your channel.",
            )
        db.execute("DELETE FROM videos WHERE id = %s", (video_id,))

    (settings.videos_dir / row["video_filename"]).unlink(missing_ok=True)
    (settings.thumbnails_dir / row["thumbnail_filename"]).unlink(missing_ok=True)
    return {"ok": True, "deleted_id": video_id}

"""Idempotent sample channel and animated VP8 WebM clip seeder."""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.auth import hash_password, pick_avatar_color
from app.config import DB_CHUNK_SIZE, ensure_directories, settings
from app.db import db_session, store_video_chunks

SEED_CHANNELS = [
    ("techbytes", "TechBytes"),
    ("synthwave_lab", "Synthwave Lab"),
    ("nature_loops", "Nature Loops"),
]

SEED_VIDEOS = [
    {
        "id": "seed_orbit1",
        "username": "techbytes",
        "title": "Neon Orbit: Building a Lightweight Streaming Engine",
        "description": (
            "Visual walk-through of how LiteTube serves chunked video over HTTP 206 "
            "byte-range requests using FastAPI and MySQL."
        ),
        "category": "Tech",
        "tags": "python,fastapi,streaming,architecture",
        "views": 1420,
        "hours_ago": 4,
        "theme": "orbit",
    },
    {
        "id": "seed_synth2",
        "username": "synthwave_lab",
        "title": "Midnight Synthwave Audio Equalizer Loop",
        "description": (
            "An ambient dark-mode synth visualizer with pulsing neon frequency bars "
            "and a retro grid horizon."
        ),
        "category": "Music",
        "tags": "synthwave,visualizer,neon,ambient",
        "views": 2890,
        "hours_ago": 14,
        "theme": "equalizer",
    },
    {
        "id": "seed_aurora",
        "username": "nature_loops",
        "title": "Northern Aurora Ribbons — 5s Calm Preview",
        "description": (
            "Flowing emerald and violet aurora borealis waves over a midnight horizon."
        ),
        "category": "Nature",
        "tags": "aurora,nature,calm,loop",
        "views": 3510,
        "hours_ago": 28,
        "theme": "aurora",
    },
    {
        "id": "seed_http26",
        "username": "techbytes",
        "title": "How HTTP 206 Byte-Range Seeking Works Under the Hood",
        "description": (
            "Interactive animation showing how browsers request byte slices when you "
            "scrub the timeline in an HTML5 video player."
        ),
        "category": "Education",
        "tags": "http,range,browser,education",
        "views": 980,
        "hours_ago": 46,
        "theme": "packets",
    },
    {
        "id": "seed_arcade",
        "username": "synthwave_lab",
        "title": "Pixel Arcade Starfield Warp Shader Demo",
        "description": (
            "Retro space-shooter starfield warp and HUD telemetry motion test rendered "
            "at 24 FPS."
        ),
        "category": "Gaming",
        "tags": "arcade,retro,gaming,shader",
        "views": 1765,
        "hours_ago": 72,
        "theme": "starfield",
    },
    {
        "id": "seed_sunset",
        "username": "nature_loops",
        "title": "Alpine Sunset Gradient Time-Lapse Simulation",
        "description": (
            "Warm amber-to-twilight sunset shifting across layered mountain ridges."
        ),
        "category": "Nature",
        "tags": "sunset,mountains,timelapse,scenery",
        "views": 640,
        "hours_ago": 110,
        "theme": "sunset",
    },
]


def _draw_frame(theme: str, frame_idx: int, total_frames: int) -> np.ndarray:
    """Render one 640x360 BGR frame for the given procedural animation theme."""
    w, h = 640, 360
    t = frame_idx / total_frames
    img = np.zeros((h, w, 3), dtype=np.uint8)

    if theme == "orbit":
        img[:, :] = (24, 16, 14)
        for gx in range(0, w, 40):
            cv2.line(img, (gx, 0), (gx, h), (38, 28, 26), 1)
        for gy in range(0, h, 40):
            cv2.line(img, (0, gy), (w, gy), (38, 28, 26), 1)
        cx, cy = w // 2, h // 2
        cv2.circle(img, (cx, cy), 105, (90, 70, 40), 2)
        cv2.circle(img, (cx, cy), 22, (255, 190, 50), -1)
        angle = t * 2 * math.pi
        ox = int(cx + 105 * math.cos(angle))
        oy = int(cy + 105 * math.sin(angle))
        cv2.circle(img, (ox, oy), 16, (255, 80, 220), -1)
        ox2 = int(cx + 64 * math.cos(-angle * 2))
        oy2 = int(cy + 64 * math.sin(-angle * 2))
        cv2.circle(img, (ox2, oy2), 10, (80, 235, 255), -1)

    elif theme == "equalizer":
        img[:, :] = (28, 12, 24)
        cv2.circle(img, (w // 2, 140), 75, (70, 35, 245), -1)
        bars = 16
        bar_w = 24
        start_x = (w - bars * 32) // 2
        for i in range(bars):
            level = 0.5 + 0.45 * math.sin(t * 4 * math.pi + i * 0.65)
            bar_h = int(35 + level * 150)
            x1 = start_x + i * 32
            y1 = h - 36 - bar_h
            color = (245, 170 - i * 6, 60 + i * 10)
            cv2.rectangle(img, (x1, y1), (x1 + bar_w, h - 36), color, -1)

    elif theme == "aurora":
        y_grid = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        img[:, :, 0] = (20 + 25 * (1 - y_grid)).astype(np.uint8)
        img[:, :, 1] = (12 + 12 * y_grid).astype(np.uint8)
        img[:, :, 2] = (10 + 18 * (1 - y_grid)).astype(np.uint8)
        for band, color in enumerate([(120, 235, 65), (220, 120, 180), (160, 255, 130)]):
            pts = []
            for x in range(0, w + 16, 16):
                y = int(
                    135
                    + band * 34
                    + 35 * math.sin(x * 0.015 + t * 2 * math.pi + band)
                )
                pts.append([x, y])
            cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, color, 10)

    elif theme == "packets":
        img[:, :] = (20, 20, 20)
        cv2.rectangle(img, (60, 150), (580, 210), (45, 45, 55), -1)
        cv2.rectangle(img, (60, 150), (580, 210), (120, 120, 140), 2)
        for idx in range(5):
            prog = (t + idx * 0.2) % 1.0
            px = int(75 + prog * 440)
            cv2.rectangle(img, (px, 160), (px + 48, 200), (255, 170, 45), -1)
        progress_x = int(60 + t * 520)
        cv2.rectangle(img, (60, 255), (progress_x, 265), (51, 34, 240), -1)
        cv2.circle(img, (progress_x, 260), 9, (60, 60, 255), -1)

    elif theme == "starfield":
        img[:, :] = (16, 10, 12)
        cx, cy = w // 2, h // 2
        for s in range(32):
            ang = s * 0.785 + (s % 5) * 0.3
            dist = ((s * 37 + frame_idx * 9) % 280) + 12
            sx = int(cx + dist * math.cos(ang))
            sy = int(cy + dist * 0.58 * math.sin(ang))
            if 0 <= sx < w and 0 <= sy < h:
                radius = 2 if dist < 140 else 3
                cv2.circle(img, (sx, sy), radius, (240, 245, 255), -1)
        ship_y = int(cy + 28 * math.sin(t * 2 * math.pi))
        pts = np.array([[150, ship_y - 16], [196, ship_y], [150, ship_y + 16]], np.int32)
        cv2.fillPoly(img, [pts], (80, 230, 255))

    else:  # sunset
        sky_shift = 0.5 + 0.5 * math.sin(t * math.pi)
        for y in range(h):
            r_frac = y / h
            b = int(60 + 80 * (1 - r_frac) * sky_shift)
            g = int(45 + 95 * r_frac * sky_shift)
            r = int(120 + 110 * r_frac)
            img[y, :] = (min(255, b), min(255, g), min(255, r))
        sun_y = int(125 + 65 * t)
        cv2.circle(img, (w // 2, sun_y), 52, (90, 210, 255), -1)
        ridge1 = np.array([[0, 360], [0, 250], [160, 185], [320, 245], [490, 175], [640, 235], [640, 360]], np.int32)
        ridge2 = np.array([[0, 360], [0, 290], [120, 235], [270, 285], [440, 225], [640, 275], [640, 360]], np.int32)
        cv2.fillPoly(img, [ridge1], (42, 26, 38))
        cv2.fillPoly(img, [ridge2], (24, 16, 22))

    return img


def _generate_seed_clip(
    video_path: Path, thumb_path: Path, spec: dict[str, object]
) -> int:
    """Create a 5-second VP8 WebM video clip and matching PNG thumbnail."""
    fps = 24
    total_frames = 120
    theme = str(spec["theme"])
    title = str(spec["title"])
    category = str(spec["category"])

    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"VP80"),
        fps,
        (640, 360),
    )
    mid_frame: np.ndarray | None = None
    try:
        for i in range(total_frames):
            frame = _draw_frame(theme, i, total_frames)
            if i == total_frames // 2:
                mid_frame = frame.copy()
            writer.write(frame)
    finally:
        writer.release()

    if mid_frame is None:
        mid_frame = _draw_frame(theme, 0, total_frames)

    rgb = cv2.cvtColor(mid_frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_img)
    draw.rectangle([(0, 290), (640, 360)], fill=(12, 12, 16))
    font = ImageFont.load_default()
    draw.rounded_rectangle([(18, 18), (118, 44)], radius=12, fill=(220, 38, 38))
    draw.text((30, 25), category.upper()[:10], fill=(255, 255, 255), font=font)
    draw.text((20, 315), title[:62], fill=(241, 241, 241), font=font)
    pil_img.save(thumb_path, format="PNG", optimize=True)
    return 5


def seed_if_empty() -> None:
    """Populate initial demo channels and clips, and backfill any missing DB media blobs."""
    if os.environ.get("LITETUBE_SKIP_SEED") == "1":
        return

    ensure_directories()
    with db_session() as db:
        user_count = db.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
        if user_count == 0:
            now = datetime.now(timezone.utc)
            password_hash = hash_password("demo1234")
            user_ids: dict[str, int] = {}

            for username, display_name in SEED_CHANNELS:
                cur = db.execute(
                    """
                    INSERT INTO users (username, display_name, password_hash, avatar_color, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        display_name,
                        password_hash,
                        pick_avatar_color(username),
                        (now - timedelta(days=10)).isoformat(),
                    ),
                )
                user_ids[username] = int(cur.lastrowid)

            for spec in SEED_VIDEOS:
                vid_id = str(spec["id"])
                video_filename = f"{vid_id}.webm"
                thumb_filename = f"{vid_id}.png"
                video_path = settings.videos_dir / video_filename
                thumb_path = settings.thumbnails_dir / thumb_filename

                duration = _generate_seed_clip(video_path, thumb_path, spec)
                file_size = video_path.stat().st_size
                thumb_bytes = thumb_path.read_bytes()
                created_at = (now - timedelta(hours=int(spec["hours_ago"]))).isoformat()

                db.execute(
                    """
                    INSERT INTO videos (
                        id, user_id, title, description, category, tags,
                        video_filename, video_mime, file_size, duration_seconds,
                        thumbnail_filename, thumbnail_data, chunk_size, views, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'video/webm', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        vid_id,
                        user_ids[str(spec["username"])],
                        str(spec["title"]),
                        str(spec["description"]),
                        str(spec["category"]),
                        str(spec["tags"]),
                        video_filename,
                        file_size,
                        duration,
                        thumb_filename,
                        thumb_bytes,
                        DB_CHUNK_SIZE,
                        int(spec["views"]),
                        created_at,
                    ),
                )
                store_video_chunks(db, vid_id, video_path, DB_CHUNK_SIZE)
            return

        # Backfill existing seeded rows if migrated from pre-BLOB schema
        for spec in SEED_VIDEOS:
            vid_id = str(spec["id"])
            row = db.execute(
                "SELECT id, thumbnail_data FROM videos WHERE id = %s", (vid_id,)
            ).fetchone()
            if row is None:
                continue
            cnt = db.execute(
                "SELECT COUNT(*) AS cnt FROM video_chunks WHERE video_id = %s",
                (vid_id,),
            ).fetchone()["cnt"]
            if row["thumbnail_data"] is not None and cnt > 0:
                continue

            video_path = settings.videos_dir / f"{vid_id}.webm"
            thumb_path = settings.thumbnails_dir / f"{vid_id}.png"
            if not video_path.is_file() or not thumb_path.is_file():
                _generate_seed_clip(video_path, thumb_path, spec)

            file_size = video_path.stat().st_size
            thumb_bytes = thumb_path.read_bytes()
            db.execute(
                """
                UPDATE videos
                SET file_size = %s, thumbnail_data = %s, chunk_size = %s
                WHERE id = %s
                """,
                (file_size, thumb_bytes, DB_CHUNK_SIZE, vid_id),
            )
            store_video_chunks(db, vid_id, video_path, DB_CHUNK_SIZE)

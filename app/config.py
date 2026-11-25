"""Application configuration, paths, and upload/auth constants."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

CATEGORIES = ("Tech", "Music", "Gaming", "Education", "Nature", "General")
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024  # 5 MB
STREAM_CHUNK_SIZE = 64 * 1024  # 64 KB
UPLOAD_CHUNK_SIZE = 256 * 1024  # 256 KB

ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/webm"}
ALLOWED_THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

SESSION_COOKIE_NAME = "litetube_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600

AVATAR_COLORS = (
    "#ef4444",
    "#f97316",
    "#eab308",
    "#22c55e",
    "#06b6d4",
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
)


@dataclass
class Settings:
    """Runtime directory configuration (mutable for isolated test runs)."""

    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / ".secret_key"


def _resolve_initial_data_dir() -> Path:
    env_dir = os.environ.get("LITETUBE_DATA_DIR")
    return Path(env_dir).resolve() if env_dir else BASE_DIR / "data"


settings = Settings(data_dir=_resolve_initial_data_dir())
_secret_cache: dict[Path, str] = {}


def set_data_dir(path: Path) -> None:
    """Update runtime data directory (used by test fixtures)."""
    settings.data_dir = path.resolve()


def ensure_directories() -> None:
    """Create required data, video, and thumbnail directories."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)


def get_secret_key() -> str:
    """Return signing key from env or persisted local secret file."""
    env_key = os.environ.get("LITETUBE_SECRET_KEY")
    if env_key:
        return env_key

    key_path = settings.secret_key_path
    if key_path in _secret_cache:
        return _secret_cache[key_path]

    ensure_directories()
    if key_path.exists():
        secret = key_path.read_text(encoding="utf-8").strip()
        if secret:
            _secret_cache[key_path] = secret
            return secret

    secret = secrets.token_urlsafe(48)
    key_path.write_text(secret, encoding="utf-8")
    _secret_cache[key_path] = secret
    return secret

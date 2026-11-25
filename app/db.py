"""Database connection pool, MySQL cloud configuration, and schema initialization."""

from __future__ import annotations

import os
import queue
import sqlite3
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

import pymysql
import pymysql.cursors
import pymysql.err

from app.config import BASE_DIR, ensure_directories

IntegrityError = (sqlite3.IntegrityError, pymysql.err.IntegrityError)


class DatabaseConfigError(RuntimeError):
    """Raised when MySQL connection settings are missing or invalid."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Parsed database connection configuration."""

    backend: str  # "mysql" or "sqlite"
    host: str = ""
    port: int = 3306
    user: str = ""
    password: str = ""
    database: str = ""
    ssl_enabled: bool = False
    ssl_ca: str | None = None
    ssl_verify: bool = True
    sqlite_path: str = ""


MYSQL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(32) NOT NULL UNIQUE,
        display_name VARCHAR(64) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        avatar_color VARCHAR(16) NOT NULL,
        created_at VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id VARCHAR(32) NOT NULL PRIMARY KEY,
        user_id INT UNSIGNED NOT NULL,
        title VARCHAR(160) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(40) NOT NULL DEFAULT 'General',
        tags VARCHAR(255) NOT NULL DEFAULT '',
        video_filename VARCHAR(128) NOT NULL,
        video_mime VARCHAR(64) NOT NULL,
        file_size BIGINT UNSIGNED NOT NULL,
        duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
        thumbnail_filename VARCHAR(128) NOT NULL,
        views BIGINT UNSIGNED NOT NULL DEFAULT 0,
        created_at VARCHAR(64) NOT NULL,
        INDEX idx_videos_created_at (created_at),
        INDEX idx_videos_category (category),
        INDEX idx_videos_user_id (user_id),
        CONSTRAINT fk_videos_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    avatar_color TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General',
    tags TEXT NOT NULL DEFAULT '',
    video_filename TEXT NOT NULL,
    video_mime TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    thumbnail_filename TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at);
CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category);
CREATE INDEX IF NOT EXISTS idx_videos_user_id ON videos(user_id);
"""


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    norm = value.strip().lower()
    if norm in ("1", "true", "yes", "on", "required", "verify_ca", "verify_identity"):
        return True
    if norm in ("0", "false", "no", "off", "disable", "disabled"):
        return False
    return default


def parse_database_config() -> DatabaseConfig:
    """Resolve database config from DATABASE_URL or MYSQL_* environment variables."""
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        if db_url.startswith("sqlite:///"):
            return DatabaseConfig(backend="sqlite", sqlite_path=db_url[10:])
        if db_url == "sqlite://:memory:":
            return DatabaseConfig(backend="sqlite", sqlite_path=":memory:")

        normalized = db_url
        for prefix in ("mysql+pymysql://", "mysql+mysqlconnector://"):
            if normalized.startswith(prefix):
                normalized = "mysql://" + normalized[len(prefix) :]
                break

        if not normalized.startswith("mysql://"):
            raise DatabaseConfigError(
                "Unsupported DATABASE_URL scheme. Expected mysql:// or mysql+pymysql://."
            )

        parsed = urlsplit(normalized)
        host = parsed.hostname or ""
        database = parsed.path.lstrip("/")
        if not host or not database:
            raise DatabaseConfigError(
                "DATABASE_URL must include a MySQL hostname and database name."
            )

        query = parse_qs(parsed.query)
        ssl_q = (
            query.get("ssl-mode")
            or query.get("ssl_mode")
            or query.get("sslmode")
            or query.get("ssl")
            or [None]
        )[0]
        ssl_ca = (query.get("ssl_ca") or query.get("sslca") or [None])[0]
        ssl_verify_q = (query.get("ssl_verify") or [None])[0]

        default_ssl = host not in ("localhost", "127.0.0.1", "::1")
        ssl_enabled = _parse_bool(
            ssl_q or os.environ.get("MYSQL_SSL"),
            default=bool(ssl_ca or default_ssl),
        )
        ssl_ca_resolved = ssl_ca or os.environ.get("MYSQL_SSL_CA") or None
        ssl_verify = _parse_bool(
            ssl_verify_q or os.environ.get("MYSQL_SSL_VERIFY"),
            default=True,
        )

        return DatabaseConfig(
            backend="mysql",
            host=host,
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=unquote(database),
            ssl_enabled=ssl_enabled,
            ssl_ca=ssl_ca_resolved,
            ssl_verify=ssl_verify,
        )

    host = os.environ.get("MYSQL_HOST", "").strip()
    if host:
        user = os.environ.get("MYSQL_USER", "").strip()
        database = os.environ.get("MYSQL_DATABASE", "").strip()
        if not user or not database:
            raise DatabaseConfigError(
                "MYSQL_USER and MYSQL_DATABASE are required when MYSQL_HOST is set."
            )

        port_raw = os.environ.get("MYSQL_PORT", "3306").strip() or "3306"
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise DatabaseConfigError("MYSQL_PORT must be an integer.") from exc

        default_ssl = host not in ("localhost", "127.0.0.1", "::1")
        ssl_ca = os.environ.get("MYSQL_SSL_CA", "").strip() or None
        ssl_enabled = _parse_bool(
            os.environ.get("MYSQL_SSL"), default=bool(ssl_ca or default_ssl)
        )
        ssl_verify = _parse_bool(os.environ.get("MYSQL_SSL_VERIFY"), default=True)

        return DatabaseConfig(
            backend="mysql",
            host=host,
            port=port,
            user=user,
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=database,
            ssl_enabled=ssl_enabled,
            ssl_ca=ssl_ca,
            ssl_verify=ssl_verify,
        )

    raise DatabaseConfigError(
        "MySQL connection is not configured. Copy .env.example to .env and set "
        "DATABASE_URL (e.g. mysql://user:pass@host:3306/dbname?ssl-mode=REQUIRED) "
        "or MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, and MYSQL_DATABASE."
    )


def build_mysql_ssl_context(config: DatabaseConfig) -> ssl.SSLContext | None:
    """Build an SSLContext when TLS is enabled for cloud MySQL connections."""
    if not config.ssl_enabled:
        return None
    ca_path = config.ssl_ca
    if ca_path and not os.path.isabs(ca_path):
        ca_path = str((BASE_DIR / ca_path).resolve())
    ctx = ssl.create_default_context(cafile=ca_path)
    if not config.ssl_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _SQLiteCompatCursor:
    """Normalize sqlite3 cursor rows to dictionaries matching PyMySQL DictCursor."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid or 0)

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._cursor.fetchall()]


class DatabaseSession:
    """Thin uniform wrapper over PyMySQL DictCursor or SQLite test connections."""

    def __init__(self, conn: Any, backend: str) -> None:
        self._conn = conn
        self.backend = backend

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        if self.backend == "mysql":
            cur = self._conn.cursor()
            cur.execute(sql, tuple(params))
            return cur
        sqlite_sql = sql.replace("%s", "?")
        cur = self._conn.execute(sqlite_sql, tuple(params))
        return _SQLiteCompatCursor(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


class _MySQLPool:
    """Thread-safe bounded LIFO pool with automatic reconnect ping on checkout."""

    def __init__(self, config: DatabaseConfig, max_size: int = 8) -> None:
        self.config = config
        self._pool: queue.LifoQueue[pymysql.connections.Connection] = queue.LifoQueue(
            maxsize=max_size
        )

    def _create_connection(self) -> pymysql.connections.Connection:
        ssl_ctx = build_mysql_ssl_context(self.config)
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            ssl=ssl_ctx,
        )

    def acquire(self) -> pymysql.connections.Connection:
        try:
            conn = self._pool.get_nowait()
            conn.ping(reconnect=True)
            return conn
        except queue.Empty:
            return self._create_connection()
        except pymysql.MySQLError:
            return self._create_connection()

    def release(self, conn: pymysql.connections.Connection, broken: bool = False) -> None:
        if broken:
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
            except Exception:
                pass


_pool_lock_config: DatabaseConfig | None = None
_mysql_pool: _MySQLPool | None = None


def reset_db_pool() -> None:
    """Close and clear the cached MySQL pool (used when configuration changes)."""
    global _pool_lock_config, _mysql_pool
    if _mysql_pool is not None:
        _mysql_pool.close_all()
    _mysql_pool = None
    _pool_lock_config = None


def _get_mysql_pool(config: DatabaseConfig) -> _MySQLPool:
    global _pool_lock_config, _mysql_pool
    if _mysql_pool is None or _pool_lock_config != config:
        reset_db_pool()
        _pool_lock_config = config
        _mysql_pool = _MySQLPool(config)
    return _mysql_pool


@contextmanager
def db_session() -> Iterator[DatabaseSession]:
    """Yield a transactional database session backed by MySQL (or SQLite in tests)."""
    config = parse_database_config()

    if config.backend == "mysql":
        pool = _get_mysql_pool(config)
        conn = pool.acquire()
        broken = False
        try:
            yield DatabaseSession(conn, "mysql")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                broken = True
            raise
        finally:
            pool.release(conn, broken=broken)
        return

    conn = sqlite3.connect(config.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        yield DatabaseSession(conn, "sqlite")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create media directories and initialize MySQL (or SQLite test) tables."""
    ensure_directories()
    config = parse_database_config()

    if config.backend == "mysql":
        with db_session() as db:
            for ddl in MYSQL_SCHEMA_STATEMENTS:
                db.execute(ddl)
        return

    conn = sqlite3.connect(config.sqlite_path, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SQLITE_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def check_db_health() -> dict[str, str]:
    """Run a lightweight connectivity check against the active database."""
    with db_session() as db:
        db.execute("SELECT 1")
        return {"status": "ok", "backend": db.backend}

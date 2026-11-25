"""Unit tests for cloud MySQL config parsing, SSL context, DDL, and pooling."""

from __future__ import annotations

import ssl
from typing import Any

import pymysql.err
import pytest

from app.config import set_data_dir
from app.db import (
    MYSQL_SCHEMA_STATEMENTS,
    DatabaseConfigError,
    build_mysql_ssl_context,
    check_db_health,
    init_db,
    parse_database_config,
    reset_db_pool,
)


def _clear_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_URL",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
        "MYSQL_SSL",
        "MYSQL_SSL_CA",
        "MYSQL_SSL_VERIFY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_parse_database_url_mysql_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://avnadmin:p%40ss%231@cloud.db.example.com:25060/litetube?ssl-mode=REQUIRED",
    )

    cfg = parse_database_config()
    assert cfg.backend == "mysql"
    assert cfg.host == "cloud.db.example.com"
    assert cfg.port == 25060
    assert cfg.user == "avnadmin"
    assert cfg.password == "p@ss#1"
    assert cfg.database == "litetube"
    assert cfg.ssl_enabled is True
    assert cfg.ssl_verify is True


def test_parse_mysql_individual_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("MYSQL_DATABASE", "litetube")

    local_cfg = parse_database_config()
    assert local_cfg.backend == "mysql"
    assert local_cfg.port == 3307
    assert local_cfg.ssl_enabled is False

    monkeypatch.setenv("MYSQL_HOST", "aws.tidbcloud.com")
    cloud_cfg = parse_database_config()
    assert cloud_cfg.ssl_enabled is True


def test_missing_mysql_config_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_db_env(monkeypatch)
    with pytest.raises(DatabaseConfigError, match="MySQL connection is not configured"):
        parse_database_config()


def test_mysql_ddl_and_ssl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    joined = "\n".join(MYSQL_SCHEMA_STATEMENTS)
    assert "ENGINE=InnoDB" in joined
    assert "utf8mb4" in joined
    assert "AUTO_INCREMENT" in joined
    assert "CREATE INDEX IF NOT EXISTS" not in joined
    assert "description TEXT NOT NULL," in joined

    _clear_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://user:pass@remote.mysql.cloud:3306/appdb?ssl-mode=REQUIRED&ssl_verify=false",
    )
    cfg = parse_database_config()
    ctx = build_mysql_ssl_context(cfg)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE


def test_mysql_pool_and_health_with_mocked_pymysql(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://user:pass@remote.mysql.cloud:3306/appdb?ssl-mode=REQUIRED",
    )
    set_data_dir(tmp_path)
    reset_db_pool()

    executed_sql: list[str] = []
    ping_calls: list[bool] = []

    class FakeCursor:
        lastrowid = 1
        rowcount = 1

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed_sql.append(sql.strip())

        def fetchone(self) -> dict[str, Any]:
            return {"1": 1}

        def fetchall(self) -> list[dict[str, Any]]:
            return []

    class FakeConn:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def ping(self, reconnect: bool = False) -> None:
            ping_calls.append(reconnect)

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    connect_kwargs: list[dict[str, Any]] = []

    def fake_connect(**kwargs: Any) -> FakeConn:
        connect_kwargs.append(kwargs)
        return FakeConn()

    monkeypatch.setattr("app.db.pymysql.connect", fake_connect)

    try:
        init_db()
        status = check_db_health()
        assert status == {"status": "ok", "backend": "mysql"}
        assert len(connect_kwargs) == 1
        assert connect_kwargs[0]["host"] == "remote.mysql.cloud"
        assert connect_kwargs[0]["charset"] == "utf8mb4"
        assert isinstance(connect_kwargs[0]["ssl"], ssl.SSLContext)
        assert ping_calls == [True]
        assert any("CREATE TABLE IF NOT EXISTS users" in s for s in executed_sql)
        assert any("SELECT 1" == s for s in executed_sql)
    finally:
        reset_db_pool()


def test_init_db_creates_missing_mysql_database_on_1049(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://user:pass@remote.mysql.cloud:3306/abc?ssl-mode=REQUIRED",
    )
    set_data_dir(tmp_path)
    reset_db_pool()

    executed_sql: list[str] = []
    connect_dbs: list[str | None] = []
    db_created = {"done": False}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed_sql.append(sql.strip())
            if "CREATE DATABASE IF NOT EXISTS `abc`" in sql:
                db_created["done"] = True

        def fetchall(self) -> list[dict[str, Any]]:
            return []

    class FakeConn:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def ping(self, reconnect: bool = False) -> None:
            pass

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_connect(**kwargs: Any) -> FakeConn:
        target_db = kwargs.get("database")
        connect_dbs.append(target_db)
        if target_db == "abc" and not db_created["done"]:
            raise pymysql.err.OperationalError(1049, "Unknown database 'abc'")
        return FakeConn()

    monkeypatch.setattr("app.db.pymysql.connect", fake_connect)

    try:
        init_db()
        assert connect_dbs == ["abc", None, "abc"]
        assert any("CREATE DATABASE IF NOT EXISTS `abc`" in s for s in executed_sql)
        assert any("CREATE TABLE IF NOT EXISTS videos" in s for s in executed_sql)
    finally:
        reset_db_pool()

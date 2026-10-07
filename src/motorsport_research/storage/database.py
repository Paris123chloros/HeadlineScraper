"""Transactional, checksum-verified migrations and SQLite connection policy."""

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def migrations() -> tuple[Migration, ...]:
    directory = files("motorsport_research.storage.migrations")
    result = tuple(
        Migration(int(item.name.split("_", 1)[0]), item.name, item.read_text(encoding="utf-8"))
        for item in sorted(directory.iterdir(), key=lambda item: item.name)
        if item.name.endswith(".sql")
    )
    if [item.version for item in result] != list(range(1, len(result) + 1)):
        raise StorageError("Packaged migrations must be contiguous starting at version one")
    return result


def connect(data_dir: Path, *, read_only: bool = False) -> sqlite3.Connection:
    database = data_dir / "research.sqlite3"
    if not database.is_file():
        raise StorageError("Storage is not initialized; run motorsport-research db-init")
    uri = database.resolve().as_uri() + ("?mode=ro" if read_only else "?mode=rw")
    connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if read_only:
        connection.execute("PRAGMA query_only = ON")
    return connection


def schema_version(connection: sqlite3.Connection, expected: tuple[Migration, ...]) -> int:
    try:
        applied = list(connection.execute("SELECT * FROM schema_migrations ORDER BY version"))
    except sqlite3.OperationalError as error:
        raise StorageError("Storage schema is not initialized; run db-init") from error
    if len(applied) > len(expected):
        raise StorageError(
            "Database schema is newer than this application; upgrade the application"
        )
    for recorded, migration in zip(applied, expected, strict=False):
        if (
            recorded["version"] != migration.version
            or recorded["name"] != migration.name
            or recorded["checksum"] != migration.checksum
        ):
            raise StorageError("Applied migration history differs from packaged migrations")
    return len(applied)


def _execute_script(connection: sqlite3.Connection, sql: str) -> None:
    # executescript implicitly commits; execute complete statements to retain atomicity.
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise StorageError("Migration ends with an incomplete SQL statement")


def initialize(data_dir: Path, *, steps: tuple[Migration, ...] | None = None) -> int:
    steps = migrations() if steps is None else steps
    if [step.version for step in steps] != list(range(1, len(steps) + 1)):
        raise StorageError("Migration versions must be contiguous")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "documents").mkdir(exist_ok=True)
    (data_dir / "reports").mkdir(exist_ok=True)
    connection = sqlite3.connect(data_dir / "research.sqlite3", isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        current = schema_version(connection, steps)
        for step in steps[current:]:
            _execute_script(connection, step.sql)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                (step.version, step.name, step.checksum, datetime.now(UTC).isoformat()),
            )
        connection.commit()
        return len(steps)
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

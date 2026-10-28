"""SQLite initialization. Never replaces an existing database."""
import sqlite3
from pathlib import Path


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        result = connection.execute('PRAGMA quick_check').fetchone()
        if result != ('ok',):
            raise sqlite3.DatabaseError('SQLite integrity check failed; original file preserved')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)')
        connection.execute('INSERT OR IGNORE INTO schema_version VALUES (1)')
        connection.commit()
    finally:
        connection.close()

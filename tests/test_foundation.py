from pathlib import Path
import sqlite3
import pytest
from config import load_settings
from src.storage import initialize_database
from src.logging_setup import configure_logging


def test_database_idempotent_preserves_data(tmp_path):
    path = tmp_path / 'nested' / 'market.db'
    initialize_database(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sample(value INTEGER)')
        db.execute('INSERT INTO sample VALUES (42)')
    initialize_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM sample').fetchall() == [(42,)]
        assert db.execute('SELECT * FROM schema_version').fetchall() == [(1,)]


def test_invalid_log_level(monkeypatch):
    monkeypatch.setenv('ETF_LOG_LEVEL', 'invalid')
    with pytest.raises(ValueError):
        load_settings()


def test_logger_no_duplicate_handlers(tmp_path):
    path = tmp_path / 'logs' / 'app.log'
    logger = configure_logging(path, 'INFO')
    count = len(logger.handlers)
    configure_logging(path, 'INFO').info('initialized')
    assert len(logger.handlers) == count
    assert 'initialized' in path.read_text()


def test_homepage(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('ETF_DB_PATH', str(tmp_path / 'market.db'))
    monkeypatch.setenv('ETF_LOG_PATH', str(tmp_path / 'market.log'))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run()
    assert not app.exception
    assert app.success

"""Environment based configuration; paths resolve relative to the project."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

@dataclass(frozen=True)
class Settings:
    db_path: Path
    log_path: Path
    log_level: str


def load_settings() -> Settings:
    level = os.getenv('ETF_LOG_LEVEL', 'INFO').upper()
    if level not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
        raise ValueError('ETF_LOG_LEVEL invalid')
    def resolve(name, default):
        path = Path(os.getenv(name, default)).expanduser()
        return path if path.is_absolute() else ROOT / path
    return Settings(resolve('ETF_DB_PATH', 'data/market.sqlite3'),
                    resolve('ETF_LOG_PATH', 'logs/market.log'), level)

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(path: Path, level: str) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('etf_monitor')
    logger.setLevel(level)
    logger.propagate = False
    target = str(path.resolve())
    if not any(getattr(handler, 'baseFilename', None) == target for handler in logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    return logger

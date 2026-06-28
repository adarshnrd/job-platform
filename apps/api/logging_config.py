"""Centralized logging configuration.

Imported once in main.py at startup. Configures loguru with:
- Console output with color
- Rotating file output (10MB per file, 7 days retention)
- Structured format for file logs
"""
import sys
from loguru import logger
from config import settings


def setup_logging():
    """Configure loguru for the application. Call once at startup."""
    logger.remove()

    log_level = "DEBUG" if settings.DEBUG else "INFO"

    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> — <level>{message}</level>",
        colorize=True,
    )

    logger.add(
        "logs/jobplatform_{time:YYYY-MM-DD}.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} — {message}",
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,
    )

    logger.add(
        "logs/errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} — {message}\n{exception}",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )

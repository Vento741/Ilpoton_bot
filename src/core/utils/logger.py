import sys
from typing import Any

from loguru import logger


def setup_logger() -> None:
    """Настройка логгера"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True
    )
    logger.add(
        "logs/bot.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="INFO",
        rotation="1 day",
        compression="zip"
    )


def log_error(error: Any) -> None:
    """
    Логирование ошибок
    :param error: Объект ошибки
    """
    logger.error(f"Error: {error}")
    logger.exception(error) 
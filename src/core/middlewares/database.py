from typing import Any, Awaitable, Callable, Dict

from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from core.middlewares.base import BaseCustomMiddleware
from database.base import async_session
from loguru import logger


class DatabaseMiddleware(BaseCustomMiddleware):
    """Middleware для работы с базой данных"""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Добавляет сессию базы данных в данные события
        :param handler: Обработчик события
        :param event: Событие
        :param data: Данные события
        :return: Результат обработки
        """
        logger.info("=================== НАЧАЛО DatabaseMiddleware ===================")
        if isinstance(event, Message):
            logger.info(f"Обработка сообщения от пользователя {event.from_user.id}: {event.text}")
        elif isinstance(event, CallbackQuery):
            logger.info(f"Обработка callback от пользователя {event.from_user.id}: {event.data}")
        
        try:
            async with async_session() as session:
                data["session"] = session
                result = await handler(event, data)
                return result
        finally:
            logger.info("=================== КОНЕЦ DatabaseMiddleware ===================\n") 
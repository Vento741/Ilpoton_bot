from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class BaseCustomMiddleware(BaseMiddleware):
    """Базовый класс для всех middleware"""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Базовый метод для обработки событий
        :param handler: Обработчик события
        :param event: Событие
        :param data: Данные события
        :return: Результат обработки
        """
        return await handler(event, data) 
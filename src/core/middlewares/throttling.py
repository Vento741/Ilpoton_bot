from typing import Any, Awaitable, Callable, Dict

from aiogram import types
from aiogram.dispatcher.flags import get_flag
from aiogram.utils.chat_action import ChatActionSender
from cachetools import TTLCache

from core.middlewares.base import BaseCustomMiddleware


class ThrottlingMiddleware(BaseCustomMiddleware):
    """Middleware для ограничения частоты запросов"""
    def __init__(self, rate_limit: int = 1):
        """
        :param rate_limit: Ограничение в секундах между запросами
        """
        self.cache = TTLCache(maxsize=10000, ttl=rate_limit)
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Проверяет частоту запросов от пользователя
        :param handler: Обработчик события
        :param event: Событие
        :param data: Данные события
        :return: Результат обработки
        """
        throttling_key = self._get_throttling_key(event)
        if throttling_key is None:
            return await handler(event, data)

        if throttling_key in self.cache:
            if isinstance(event, types.Message):
                await event.answer(
                    "Пожалуйста, подождите немного перед следующим запросом 🙏"
                )
            return None

        self.cache[throttling_key] = None
        return await handler(event, data)

    @staticmethod
    def _get_throttling_key(event: types.TelegramObject) -> str | None:
        """
        Получает ключ для троттлинга
        :param event: Событие
        :return: Ключ или None, если троттлинг не нужен
        """
        if isinstance(event, types.Message):
            return f"message_{event.from_user.id}"
        elif isinstance(event, types.CallbackQuery):
            return f"callback_{event.from_user.id}"
        return None 
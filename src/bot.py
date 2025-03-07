# src/bot.py

import asyncio
import logging
import os
from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from core.bot import bot, start_scheduler
from config.settings import settings
from core.middlewares import DatabaseMiddleware, AuthMiddleware, ThrottlingMiddleware
from core.utils import setup_logger

# Импорт роутеров
from handlers.admin import router as admin_router
from handlers.client import router as client_router

# Настройка логирования
setup_logger()
logger = logging.getLogger(__name__)

# Создание директории для логов
if not os.path.exists("logs"):
    os.makedirs("logs")

# Инициализация диспетчера
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Регистрация middleware
dp.message.middleware(DatabaseMiddleware())
dp.callback_query.middleware(DatabaseMiddleware())
dp.message.middleware(AuthMiddleware())
dp.callback_query.middleware(AuthMiddleware())
dp.message.middleware(ThrottlingMiddleware())
dp.callback_query.middleware(ThrottlingMiddleware())

async def main() -> None:
    """
    Главная функция запуска бота
    """
    logger.info("Запуск бота...")
    
    # Запускаем планировщик
    await start_scheduler()
    
    # Очищаем все предыдущие апдейты
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Добавляем фильтры для роутеров
    admin_router.message.filter(F.from_user.id.in_(settings.admin_ids))
    admin_router.callback_query.filter(F.from_user.id.in_(settings.admin_ids))
    
    # Регистрация роутеров
    # Сначала регистрируем клиентский роутер
    dp.include_router(client_router)
    
    # Затем регистрируем админский роутер
    dp.include_router(admin_router)
    
    try:
        logger.info("Бот запущен!")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.exception(f"Ошибка при запуске бота: {e}")
        raise
    finally:
        logger.info("Остановка бота...")
        await bot.session.close()
        logger.info("Бот остановлен!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен!")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}") 
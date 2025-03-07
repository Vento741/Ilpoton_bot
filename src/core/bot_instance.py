from aiogram import Bot
from aiogram.enums import ParseMode
from config.settings import settings
from loguru import logger
import traceback

# Инициализация бота
try:
    # Получаем значение токена и выводим для проверки его формат (без самого токена)
    token = settings.bot_token.get_secret_value()
    logger.info(f"Токен получен, тип: {type(token)}, длина: {len(token)}")
    
    # Инициализация бота
    bot = Bot(token=token)
    logger.info("Бот инициализирован")
except Exception as e:
    logger.error(f"Ошибка при инициализации бота: {e}")
    logger.error(f"Детали ошибки: {traceback.format_exc()}") 
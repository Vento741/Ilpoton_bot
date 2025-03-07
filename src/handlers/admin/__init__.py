# src/handlers/admin/__init__.py

from aiogram import Router, F
from config.settings import settings

# Создаем основной роутер
router = Router(name='admin')

# Импортируем модули
from . import (
    base,
    content,
    services,
    time_slots,
    appointments,
    price_requests,
    commands,
    broadcasts,
    slot_machine
)

# Добавляем фильтры для админских ID в основной роутер
router.message.filter(F.from_user.id.in_(settings.admin_ids))
router.callback_query.filter(F.from_user.id.in_(settings.admin_ids))

# Правильный порядок подключения роутеров:
router.include_router(base.router)           # Базовые команды и общие обработчики
router.include_router(content.router)        # Управление контентом
router.include_router(services.router)       # Управление услугами
router.include_router(time_slots.router)     # Управление расписанием
router.include_router(price_requests.router) # Запросы на расчет
router.include_router(commands.router)       # Управление командами
router.include_router(broadcasts.router)     # Управление рассылками
router.include_router(slot_machine.router)   # Управление слот-машиной
router.include_router(appointments.router)   # Управление записями (включая catch_all)

__all__ = ["router"] 
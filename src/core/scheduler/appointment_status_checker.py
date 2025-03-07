from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.utils.time_slots import update_completed_appointments
from database.base import async_session

async def check_appointments_status():
    """
    Периодическая задача для проверки и обновления статусов записей
    """
    try:
        async with async_session() as session:
            await update_completed_appointments(session)
    except Exception as e:
        logger.error(f"Ошибка при проверке статусов записей: {e}")

def setup_appointment_checker(scheduler: AsyncIOScheduler):
    """
    Настраивает планировщик для периодической проверки статусов записей
    
    Args:
        scheduler: Экземпляр AsyncIOScheduler
    """
    # Добавляем задачу проверки статусов каждые 10 минут
    scheduler.add_job(
        check_appointments_status,
        trigger=IntervalTrigger(minutes=10),
        id='check_appointments_status',
        name='Проверка статусов записей',
        replace_existing=True
    )
    logger.info("Планировщик проверки статусов записей настроен")
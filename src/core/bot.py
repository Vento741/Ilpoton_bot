from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
import asyncio

from core.scheduler.appointment_notifications import notify_admin_about_appointment
from core.scheduler.appointment_status_checker import setup_appointment_checker
from core.scheduler.slot_machine_scheduler import setup_slot_machine_scheduler
from core.bot_instance import bot

# Создаем планировщик
scheduler = AsyncIOScheduler()

async def start_scheduler():
    """
    Запуск планировщика с асинхронной сессией
    """
    try:
        # Настраиваем уведомления
        trigger = IntervalTrigger(seconds=10)
        
        # Добавляем задачу
        scheduler.add_job(
            notify_admin_about_appointment,
            trigger=trigger,
            id='notifications_job',
            replace_existing=True
        )
        logger.info("Планировщик уведомлений успешно добавлен")
        
        # Настраиваем проверку статусов записей
        setup_appointment_checker(scheduler)
        
        # Настраиваем планировщик слот-машины
        setup_slot_machine_scheduler(scheduler)
        logger.info("Планировщик слот-машины успешно добавлен")
        
        # Запускаем планировщик
        scheduler.start()
        logger.info("Планировщик запущен")
        
    except Exception as e:
        logger.error(f"Ошибка при настройке планировщика: {e}", exc_info=True)

# Экспортируем только необходимое
__all__ = ['scheduler', 'start_scheduler', 'bot']

# Функция для запуска бота и планировщика
async def main():
    # Запускаем планировщик
    await start_scheduler()
    
    try:
        # Держим бота запущенным
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.get_updates()  # Запускаем long polling
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
    finally:
        await bot.session.close()

# Запускаем все вместе
if __name__ == "__main__":
    asyncio.run(main())





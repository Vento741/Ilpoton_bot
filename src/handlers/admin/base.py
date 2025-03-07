# src/handlers/admin/base.py

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.context import FSMContext
from loguru import logger
from datetime import datetime, timedelta

from config.settings import settings
from core.utils import NOT_ADMIN_MESSAGE
from database.models import User, Service, News, Broadcast, Appointment, PriceRequest, TimeSlot
from keyboards.admin.admin import (
    get_admin_keyboard, 
    get_admin_inline_keyboard,
    get_content_management_keyboard,
    get_news_management_keyboard,
    get_broadcast_management_keyboard
)
from keyboards.client.client import get_main_keyboard
from core.utils.logger import log_error

router = Router(name='admin_base')

BASE_PREFIXES = [
    "base_",
    "menu_",
    "back_to_",
    "manage_content",
    "exit_admin_panel"
]

def is_base_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к базовым операциям
    """
    return any(callback.data.startswith(prefix) for prefix in BASE_PREFIXES)

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    print(f"Проверка прав администратора для пользователя {user_id}. Admin IDs: {settings.admin_ids}")
    return user_id in settings.admin_ids

@router.message(Command("admin"), F.from_user.id.in_(settings.admin_ids))
async def cmd_admin(message: Message) -> None:
    """
    Обработчик команды /admin
    """
    logger.info(f"Администратор {message.from_user.id} использовал команду /admin")
    await message.answer(
        "<b>👋 Привет, администратор!</b> Вы находитесь в <b>панели управления</b>. Выберите, как хотите продолжить:\n\n",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    ) 

@router.message(Command("admin"))
async def cmd_admin_no_access(message: Message) -> None:
    """
    Обработчик команды /admin для пользователей без прав администратора
    """
    logger.info(f"Пользователь {message.from_user.id} попытался использовать команду /admin")
    await message.answer(NOT_ADMIN_MESSAGE)

@router.message(F.text == "🔙 Пользовательский режим", admin_filter)
async def switch_to_user_mode(message: Message, state: FSMContext) -> None:
    """
    Переключение в пользовательский режим
    """
    # Очищаем состояние при переключении режимов
    await state.clear()
    
    await message.answer(
        "<b>Вы перешли в пользовательский режим, что бы вернуться в админку, введите или нажмите на кнопку <b>/admin</b></b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@router.message(F.text == "📊 Статистика", admin_filter)
async def show_statistics(message: Message, session: AsyncSession) -> None:
    """
    Показывает статистику бота
    """
    # Получаем статистику
    total_users = await session.scalar(select(User).count())
    total_services = await session.scalar(select(Service).count())

    stats_text = (
        "<b>📊 Статистика бота:</b>\n\n"
        f"<b>👥 Всего пользователей:</b> {total_users}\n"
        f"<b>💰 Услуг в каталоге:</b> {total_services}\n"
    )

    await message.answer(stats_text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

# Приоритетный обработчик для панели администратора
@router.message(F.text.regexp(r'^👨‍💼 Панель администратора$'), F.from_user.id.in_(settings.admin_ids))
async def show_admin_panel(message: Message, session: AsyncSession) -> None:
    """
    Показывает панель администратора с актуальной статистикой
    """
    try:
        logger.info(f"Администратор {message.from_user.id} открыл панель администратора")

        # Получаем текущую дату и дату неделю назад
        current_date = datetime.now()
        week_ago = current_date - timedelta(days=7)

        # Получаем статистику по записям
        appointments_stats = await session.execute(
            select(
                func.count(Appointment.id).label('total'),
                func.sum(case((Appointment.status == 'PENDING', 1), else_=0)).label('pending'),
                func.sum(case((Appointment.status == 'CONFIRMED', 1), else_=0)).label('confirmed'),
                func.sum(case((Appointment.status == 'COMPLETED', 1), else_=0)).label('completed'),
                func.sum(case(
                    (and_(Appointment.status == 'COMPLETED', Appointment.time_slot.has(TimeSlot.date >= week_ago)), 1),
                    else_=0
                )).label('completed_week')
            )
        )
        stats = appointments_stats.first()

        # Получаем количество необработанных запросов на расчет стоимости
        price_requests = await session.execute(
            select(func.count(PriceRequest.id))
            .where(PriceRequest.status == 'PENDING')
        )
        pending_price_requests = price_requests.scalar()

        # Формируем текст с информативной статистикой
        stats_text = (
            "<b>👨‍💼 Панель администратора</b>\n\n"
            "<b>📊 Статистика:</b>\n"
            f"• Новых записей: <b>{stats.pending or 0}</b>\n"
            f"• Подтвержденных: <b>{stats.confirmed or 0}</b>\n"
            f"• Выполнено за неделю: <b>{stats.completed_week or 0}</b>\n"
            f"• Всего выполнено: <b>{stats.completed or 0}</b>\n"
            f"• Запросов на расчет: <b>{pending_price_requests}</b>\n\n"
            "<b>Выберите нужный раздел:</b>"
        )

        await message.answer(
            stats_text,
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при открытии панели администратора: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при открытии панели администратора",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "exit_admin_panel", is_base_callback)
async def exit_admin_panel(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Выход из панели администратора
    """
    try:
        await callback.answer()
        # Очищаем состояние при выходе из админ-панели
        await state.clear()
        
        # Удаляем сообщение с админ-панелью
        await callback.message.delete()
        
        # Отправляем новое сообщение с клавиатурой пользователя
        await callback.message.answer(
            "<b>Вы перешли в пользовательский режим, что бы вернуться в админку, введите или нажмите на кнопку <b>/admin</b></b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при выходе из панели администратора",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "back_to_admin", admin_filter, is_base_callback)
async def back_to_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат в главное меню администратора
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} вернулся в главное меню")
        await callback.answer()
        await state.clear()
        await callback.message.edit_text(
            "<b>👨‍💼Панель администратора</b>\n"
            "Выберите нужный раздел 📝\n\n"
            "<b>Сдесь вы можете управлять контентом, записями, рассылками и другими параметрами бота</b>\n\n"
            "🔑 <b>Вы можете выйти из панели администратора</b> в любой момент, нажав на кнопку <b>Выйти из Админки</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при возврате в главное меню",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("base_"), is_base_callback)
async def base_callback(callback: CallbackQuery) -> None:
    """
    Обработчик для базовых callback'ов
    """
    logger.info(f"Администратор {callback.from_user.id} использовал базовый callback: {callback.data}")
    await callback.answer()

@router.callback_query(F.data == "manage_content", admin_filter, is_base_callback)
async def manage_content(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Управление контентом
    """
    try:
        logger.info("=== НАЧАЛО manage_content в base.py ===")
        logger.info(f"Callback data: {callback.data}")
        logger.info(f"User ID: {callback.from_user.id}")

        await callback.answer()

        # Исправляем подсчет количества элементов
        news_result = await session.execute(select(func.count()).select_from(News))
        news_count = news_result.scalar()

        broadcasts_result = await session.execute(select(func.count()).select_from(Broadcast))
        broadcasts_count = broadcasts_result.scalar()
        
        logger.info(f"Статистика: новости={news_count}, рассылки={broadcasts_count}")

        text = (
            "<b>📢 Управление контентом</b>\n\n"
            f"<b>📰 Новостей:</b> {news_count}\n"
            f"<b>📨 Рассылок:</b> {broadcasts_count}\n\n"
            "Выберите раздел для управления:"
        )
        
        logger.info("Отправка сообщения с клавиатурой")
        await callback.message.edit_text(
            text,
            reply_markup=get_content_management_keyboard(),
            parse_mode="HTML"
        )
        logger.info("Сообщение успешно отправлено")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике manage_content: {e}", exc_info=True)
        log_error(e)
        await callback.message.edit_text(
            "Произошла ошибка при открытии управления контентом",
            reply_markup=get_admin_inline_keyboard()
        )
    finally:
        logger.info("=== КОНЕЦ manage_content в base.py ===")

@router.message(Command("start"), F.from_user.id.in_(settings.admin_ids))
async def cmd_start_admin(message: Message) -> None:
    """
    Обработчик команды /start для администраторов
    Позволяет админам использовать бота как обычным пользователям
    """
    logger.info(f"Администратор {message.from_user.id} использовал команду /start")
    await message.answer(
        "<b>👋 Добро пожаловать!</b>\n\n"
        "Вы вошли как обычный пользователь.\n"
        "Для доступа к панели администратора используйте команду /admin",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# src/handlers/admin/commands.py

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from config.settings import settings
from database.models.models import Appointment, User, Service, TimeSlot
from keyboards.admin.admin import (
    get_appointments_management_keyboard,
    get_confirmation_keyboard,
    get_admin_keyboard
)
from states.admin import AdminAppointmentStates
from core.utils import NOT_ADMIN_MESSAGE



router = Router()

COMMAND_PREFIXES = [
    "admin",
    "appointment_",
    "settings_",
    "change_status_",
    "confirm_status_",
    "cancel_",
    "start"
    
]

def is_command_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к командам
    """
    return any(callback.data.startswith(prefix) for prefix in COMMAND_PREFIXES)

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.message.from_user.id
    return user_id in settings.admin_ids

@router.message(Command("admin"), admin_filter)
async def cmd_admin(message: Message) -> None:
    """
    Обработчик команды /admin
    """
    await message.answer(
        "👨‍💼 Панель администратора",
        reply_markup=get_admin_keyboard()
    )

@router.message(Command("admin"))
async def cmd_admin_no_access(message: Message) -> None:
    """
    Обработчик команды /admin для пользователей без прав администратора
    """
    await message.answer(NOT_ADMIN_MESSAGE)

@router.message(F.text == "📝 Управление записями", admin_filter)
async def show_appointments(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """
    Показывает список записей
    """
    await state.set_state(AdminAppointmentStates.viewing_list)
    
    appointments = await session.execute(
        select(Appointment).order_by(Appointment.created_at.desc())
    )
    appointments = appointments.scalars().all()
    
    if not appointments:
        await message.answer("Нет активных записей")
        return
    
    # Формируем сообщение со списком записей
    appointments_text = "📝 Список записей:\n\n"
    for app in appointments:
        appointments_text += (
            f"<b>👤 Клиент:</b> {app.user.full_name}\n"
            f"<b>📅 Дата:</b> {app.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {app.service.name}\n"
            f"<b>📊 Статус:</b> {app.status}\n\n"
        )
    
    await message.answer(appointments_text, parse_mode="HTML")

@router.callback_query(F.data.startswith("appointment_"), admin_filter, is_command_callback)
async def show_appointment_details(callback: CallbackQuery, session: AsyncSession):
    """Показать детали записи и возможные действия"""
    appointment_id = int(callback.data.split("_")[1])
    
    query = select(Appointment).where(Appointment.id == appointment_id)
    result = await session.execute(query)
    appointment = result.scalar_one_or_none()
    
    if not appointment:
        await callback.answer("Запись не найдена")
        return
    
    # Получаем связанные данные
    user = await session.get(User, appointment.user_id)
    service = await session.get(Service, appointment.service_id)
    time_slot = await session.get(TimeSlot, appointment.time_slot_id)
    
    details = (
        f"<b>📋 Детали записи #{appointment.id}</b>\n\n"
        f"<b>👤 Клиент:</b> {user.full_name}\n"
        f"<b>📱 Телефон:</b> {user.phone_number}\n"
        f"<b>💇‍♀️ Услуга:</b> {service.name}\n"
        f"<b>📅 Дата:</b> {time_slot.date.strftime('%d.%m.%Y')}\n"
        f"<b>📝 Статус:</b> {appointment.status}\n"
    )
    
    if appointment.comment:
        details += f"<b>💭 Комментарий:</b> {appointment.comment}\n"
    
    keyboard = get_appointments_management_keyboard(appointments=[appointment])
    await callback.message.edit_text(details, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("change_status_"), admin_filter, is_command_callback)
async def change_appointment_status(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Изменить статус записи"""
    appointment_id = int(callback.data.split("_")[2])
    new_status = callback.data.split("_")[3]
    
    query = select(Appointment).where(Appointment.id == appointment_id)
    result = await session.execute(query)
    appointment = result.scalar_one_or_none()
    
    if not appointment:
        await callback.answer("Запись не найдена")
        return
    
    # Подтверждение действия
    await state.update_data(appointment_id=appointment_id, new_status=new_status)
    confirmation_text = f"<b>Вы уверены, что хотите изменить статус записи #{appointment_id} на {new_status}?</b>"
    await callback.message.edit_text(
        confirmation_text,
        reply_markup=get_confirmation_keyboard(f"confirm_status_{appointment_id}")
    )

@router.callback_query(F.data.startswith("confirm_status_"), admin_filter, is_command_callback)
async def confirm_status_change(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Подтвердить изменение статуса записи"""
    data = await state.get_data()
    appointment_id = data.get("appointment_id")
    new_status = data.get("new_status")
    
    query = select(Appointment).where(Appointment.id == appointment_id)
    result = await session.execute(query)
    appointment = result.scalar_one_or_none()
    
    if not appointment:
        await callback.answer("<b>❌ Запись не найдена</b>", parse_mode="HTML")
        return
    
    # Обновляем статус
    appointment.status = new_status
    await session.commit()
    
    await callback.answer(
        f"<b>✅ Статус записи</b> <code>#{appointment_id}</code> <b>изменен на</b> <code>{new_status}</code>",
        parse_mode="HTML"
    )
    await show_appointments(callback.message, session)
    await state.clear()

@router.callback_query(F.data.startswith("cancel_"), admin_filter, is_command_callback)
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    """Отменить действие"""
    await state.clear()
    await show_appointments(callback.message, callback.message.bot.session)

@router.message(Command("start"), admin_filter)
async def cmd_start(message: Message) -> None:
    """
    Обработчик команды /start для администраторов
    """
    logger.info(f"Администратор {message.from_user.id} использовал команду /start")
    await message.answer(
        "<b>👋 Привет, администратор! Вы находитесь в панели управления. Выберите, как хотите продолжить:</b>\n\n",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    ) 
# src/handlers/admin/time_slots.py

from datetime import datetime, timedelta, time
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger

from config.settings import settings
from database.models import TimeSlot, Appointment
from keyboards.admin.admin import (
    get_admin_keyboard,
    get_time_slots_dates_keyboard,
    get_time_slots_for_date_keyboard,
    get_admin_inline_keyboard
)
from states.admin import TimeSlotStates
from core.utils.logger import log_error
from core.utils.time_slots import get_time_slots_view, check_and_clear_states, update_completed_appointments


router = Router(name='admin_time_slots')

TIME_SLOTS_PREFIXES = [
    "manage_schedule",
    "view_date_",
    "add_slot_to_date_",
    "add_appointment_comment_",
    "select_time_schedule_",
    "select_date_schedule_",
    "manual_time_schedule",
    "manual_date_schedule",
    "delete_slot_",
    "auto_create_slots_schedule",
    "auto_month_",
    "date_page_",
    "select_time_slot_"
]

def admin_filter(message: Message | CallbackQuery) -> bool:
    """
    Фильтр для проверки прав администратора
    """
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    return user_id in settings.admin_ids

# Добавим функцию проверки callback'ов расписания
def is_time_slots_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению расписанием
    """
    return any(callback.data.startswith(prefix) for prefix in TIME_SLOTS_PREFIXES)

@router.callback_query(F.data == "manage_schedule", is_time_slots_callback)
async def manage_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обработчик кнопки управления расписанием
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} открыл управление расписанием")
        
        # Сначала обновляем статусы завершенных записей
        await update_completed_appointments(session)
        
        # Сразу отвечаем на callback
        await callback.answer()
        
        time_slots = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date >= datetime.now())
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        logger.debug(f"Найдено временных слотов: {len(time_slots)}")
        
        # Создаем клавиатуру с кнопками управления
        keyboard = [
            [InlineKeyboardButton(
                text="🔄 Автосоздание слотов на месяц",
                callback_data="auto_create_slots_schedule"
            )],
            [InlineKeyboardButton(
                text="➕ Добавить слот",
                callback_data="add_time_slot_schedule"
            )]
        ]
        
        dates_keyboard = get_time_slots_dates_keyboard(time_slots, page=1)
        
        # Добавляем уникальный идентификатор к сообщению для предотвращения ошибки "message is not modified"
        current_time = datetime.now().strftime("%H:%M:%S")
        
        try:
            await callback.message.edit_text(
                f"<b>🕐 Управление расписанием</b>\n\n"
                f"Выберите действие или дату для просмотра временных слотов:\n"
                f"Обновлено в {current_time}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=keyboard + dates_keyboard.inline_keyboard
                ),
                parse_mode="HTML"
            )
        except Exception as edit_error:
            if "message is not modified" in str(edit_error):
                logger.debug("Сообщение не требует обновления")
                return
            else:
                await callback.message.answer(
                    f"<b>🕐 Управление расписанием</b>\n\n"
                    f"Выберите действие или дату для просмотра временных слотов:\n"
                    f"Обновлено в {current_time}",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=keyboard + dates_keyboard.inline_keyboard
                    ),
                    parse_mode="HTML"
                )
                
    except Exception as e:
        logger.error(f"Ошибка при загрузке расписания: {str(e)}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке расписания",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("view_date_"), is_time_slots_callback)
async def view_date_slots(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Показывает временные слоты для выбранной даты
    """
    if not admin_filter(callback):
        await callback.answer("У вас нет прав для выполнения этого действия")
        return

    try:
        # Обновляем статусы завершенных записей
        await update_completed_appointments(session)
        
        date_str = callback.data.split("_")[2]
        logger.info(f"Администратор {callback.from_user.id} просматривает слоты на {date_str}")
        logger.debug(f"Получен callback_data: {callback.data}")
        await callback.answer()
        
        # Получаем все слоты на эту дату
        selected_date = datetime.strptime(date_str, "%d.%m.%Y")
        
        text, keyboard = await get_time_slots_view(selected_date, session)
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при просмотре слотов на дату: {str(e)}", exc_info=True)
        await callback.message.edit_text(
            "Произошла ошибка при загрузке временных слотов",
            reply_markup=get_time_slots_dates_keyboard([])
        )

@router.callback_query(F.data.startswith("add_slot_to_date_"), is_time_slots_callback)
async def start_add_slot_to_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса добавления слота на конкретную дату
    """
    try:
        date_str = callback.data.split("_")[-1]
        await callback.answer()
        
        # Преобразуем строку даты в datetime
        date = datetime.strptime(date_str, "%d.%m.%Y")
        
        # Получаем существующие слоты на эту дату
        existing_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= date.replace(hour=0, minute=0),
                TimeSlot.date <= date.replace(hour=23, minute=59)
            )
        )
        existing_slots = existing_slots.scalars().all()
        
        # Получаем все записи на эту дату
        all_appointments = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= date.replace(hour=0, minute=0),
                TimeSlot.date <= date.replace(hour=23, minute=59)
            )
            .options(
                selectinload(Appointment.time_slot)
            )
        )
        all_appointments = all_appointments.scalars().all()
        
        # Создаем множества занятых времен
        existing_times = {slot.date.strftime('%H:%M') for slot in existing_slots}
        occupied_times = set()
        
        # Добавляем времена всех записей и следующие часы для подтвержденных
        for app in all_appointments:
            time_str = app.time_slot.date.strftime('%H:%M')
            occupied_times.add(time_str)
            # Для подтвержденных записей добавляем следующий час
            if app.status == "CONFIRMED":
                next_hour = (app.time_slot.date + timedelta(hours=1))
                if next_hour.date() == app.time_slot.date.date():
                    occupied_times.add(next_hour.strftime('%H:%M'))
        
        # Создаем клавиатуру со временем
        keyboard = []
        
        # Добавляем кнопку для ручного ввода времени
        keyboard.append([InlineKeyboardButton(
            text="🕐 Ввести время вручную",
            callback_data="manual_time_schedule"
        )])
        
        # Добавляем кнопки с доступными часами
        all_times = ["09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00"]
        available_times = [t for t in all_times if t not in existing_times and t not in occupied_times]
        
        for time in available_times:
            keyboard.append([InlineKeyboardButton(
                text=time,
                callback_data=f"select_time_schedule_{time}"
            )])
        
        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton(
            text="↩️ Назад",
            callback_data=f"view_date_{date_str}"
        )])
        
        # Сохраняем дату в состояние
        await state.update_data(date=date_str)
        await state.set_state(TimeSlotStates.selecting_time)
        
        message_text = (
            f"<b>📅 Выбрана дата: {date_str}</b>\n\n"
            "<b>🕐 Выберите время или введите вручную в формате:</b>\n"
            "• <code>ЧЧ</code> (10)\n"
            "• <code>ЧЧ:ММ</code> (10:30)"
        )
        
        if not available_times:
            message_text += "\n\n❗️ Все стандартные слоты на эту дату уже созданы или заняты"
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при начале добавления слота на дату: {e}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка. Пожалуйста, попробуйте еще раз.</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "add_time_slot_schedule", F.from_user.id.in_(settings.admin_ids), is_time_slots_callback)
async def start_add_time_slot(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начало процесса добавления временного слота
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} начал добавление временного слота")
        await callback.answer()
        
        # Создаем клавиатуру с датами на ближайшие 7 дней
        keyboard = []
        today = datetime.now()
        
        # Добавляем кнопку для ручного ввода даты
        keyboard.append([InlineKeyboardButton(
            text="📅 Ввести дату вручную",
            callback_data="manual_date_schedule"
        )])
        
        # Добавляем кнопки с датами
        for i in range(7):
            date = today + timedelta(days=i)
            keyboard.append([InlineKeyboardButton(
                text=date.strftime("%d.%m.%Y (%a)"),
                callback_data=f"select_date_schedule_{date.strftime('%d.%m.%Y')}"
            )])
        
        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="manage_schedule"
        )])
        
        await state.set_state(TimeSlotStates.selecting_date)
        await callback.message.edit_text(
            "<b>📅 Выберите дату или введите её вручную в формате:</b>\n"
            "• <code>ДД.ММ</code> (15.02)\n"
            "• <code>ДД.ММ.ГГГГ</code> (15.02.2025)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при добавлении слота. Пожалуйста, попробуйте еще раз.</b>",
            reply_markup=get_time_slots_dates_keyboard([]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("select_date_"), TimeSlotStates.selecting_date, is_time_slots_callback)
async def process_date_selection(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка выбора даты из кнопок
    """
    try:
        selected_date = callback.data.split("_")[2]
        await process_date_input(callback.message, state, session, selected_date, is_callback=True)
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при выборе даты. Пожалуйста, попробуйте еще раз.</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "manual_date_schedule", TimeSlotStates.selecting_date, is_time_slots_callback)
async def request_manual_date(callback: CallbackQuery) -> None:
    """
    Запрос ручного ввода даты
    """
    await callback.message.edit_text(
        "<b>📅 Введите дату в одном из форматов:</b>\n"
        "• <code>ДД.ММ</code> (15.02)\n"
        "• <code>ДД.ММ.ГГГГ</code> (15.02.2025)",
        parse_mode="HTML"
    )

@router.message(TimeSlotStates.selecting_date, admin_filter)
async def process_manual_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ручного ввода даты
    """
    await process_date_input(message, state, session, message.text)

async def process_date_input(message: Message, state: FSMContext, session: AsyncSession, date_text: str, is_callback: bool = False) -> None:
    """
    Обработка введенной даты
    """
    try:
        # Обработка короткого формата даты (ДД.ММ)
        if len(date_text.split('.')) == 2:
            current_year = datetime.now().year
            date_text = f"{date_text}.{current_year}"
        
        date = datetime.strptime(date_text, "%d.%m.%Y")
        
        if date.date() < datetime.now().date():
            text = "<b>❌ Дата не может быть в прошлом!</b>\nВыберите другую дату:"
            if is_callback:
                await message.edit_text(text, parse_mode="HTML")
            else:
                await message.answer(text, parse_mode="HTML")
            return
        
        await state.update_data(date=date.strftime("%d.%m.%Y"))
        
        # Получаем существующие слоты на эту дату
        existing_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= date.replace(hour=0, minute=0),
                TimeSlot.date <= date.replace(hour=23, minute=59)
            )
        )
        existing_slots = existing_slots.scalars().all()
        
        # Получаем подтвержденные записи на эту дату
        confirmed_appointments = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= date.replace(hour=0, minute=0),
                TimeSlot.date <= date.replace(hour=23, minute=59),
                Appointment.status == "CONFIRMED"
            )
        )
        confirmed_appointments = confirmed_appointments.scalars().all()
        
        # Создаем множества занятых времен
        existing_times = {slot.date.strftime('%H:%M') for slot in existing_slots}
        occupied_times = set()
        
        # Добавляем времена подтвержденных записей и следующие часы
        for app in confirmed_appointments:
            time_str = app.time_slot.date.strftime('%H:%M')
            occupied_times.add(time_str)
            # Добавляем следующий час
            next_hour = (app.time_slot.date + timedelta(hours=1))
            if next_hour.date() == app.time_slot.date.date():  # Проверяем, что следующий час в тот же день
                occupied_times.add(next_hour.strftime('%H:%M'))
        
        # Создаем клавиатуру со временем
        keyboard = []
        
        # Добавляем кнопку для ручного ввода времени
        keyboard.append([InlineKeyboardButton(
            text="🕐 Ввести время вручную",
            callback_data="manual_time_schedule"
        )])
        
        # Добавляем кнопки только с доступным временем
        all_times = ["09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00"]
        available_times = [time for time in all_times if time not in existing_times and time not in occupied_times]
        
        if available_times:
            for time in available_times:
                keyboard.append([InlineKeyboardButton(
                    text=time,
                    callback_data=f"select_time_schedule_{time}"
                )])
        else:
            # Если все слоты заняты, показываем сообщение
            text = (
                f"<b>❌ На {date.strftime('%d.%m.%Y')} все временные слоты уже созданы или заняты!</b>\n"
                "Выберите другую дату:"
            )
            if is_callback:
                await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="add_time_slot_schedule")
                ]]), parse_mode="HTML")
            else:
                await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="add_time_slot_schedule")
                ]]), parse_mode="HTML")
            return
        
        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="add_time_slot_schedule"
        )])
        
        text = (
            f"<b>📅 Выбрана дата: {date.strftime('%d.%m.%Y')}</b>\n\n"
            "<b>🕐 Выберите время или введите вручную в формате:</b>\n"
            "• <code>ЧЧ</code> (10)\n"
            "• <code>ЧЧ:ММ</code> (10:30)"
        )
        
        await state.set_state(TimeSlotStates.selecting_time)
        if is_callback:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
            
    except ValueError:
        text = (
            "<b>❌ Неверный формат даты!</b>\n\n"
            "Используйте один из форматов:\n"
            "• <code>ДД.ММ</code> (15.02)\n"
            "• <code>ДД.ММ.ГГГГ</code> (15.02.2025)"
        )
        if is_callback:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data.startswith("select_time_schedule_"), is_time_slots_callback)
async def process_time_selection(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка выбора времени из кнопок для создания нового слота
    """
    try:
        logger.info(f"Обработка выбора времени от администратора {callback.from_user.id}")
        selected_time = callback.data.split("_")[3]
        
        # Получаем дату из состояния
        data = await state.get_data()
        date_str = data.get("date")
        
        if not date_str:
            await callback.answer("Ошибка: дата не найдена")
            return
            
        # Преобразуем строку даты и времени в datetime
        date = datetime.strptime(date_str, "%d.%m.%Y")
        time_parts = selected_time.split(":")
        slot_datetime = date.replace(hour=int(time_parts[0]), minute=int(time_parts[1]))
        
        # Проверяем, не существует ли уже слот на это время
        existing_slot_result = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= slot_datetime.replace(second=0, microsecond=0),
                TimeSlot.date < slot_datetime.replace(second=0, microsecond=0) + timedelta(minutes=1)
            )
        )
        if existing_slot_result.scalar_one_or_none():
            await callback.answer("На это время уже существует слот!")
            return

        # Проверяем, нет ли записей на это время
        appointments_result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                TimeSlot.date >= date.replace(hour=0, minute=0),
                TimeSlot.date <= date.replace(hour=23, minute=59)
            )
            .options(
                selectinload(Appointment.time_slot)
            )
        )
        appointments = appointments_result.scalars().all()
        
        # Проверяем конфликты с записями
        for app in appointments:
            app_time = app.time_slot.date
            app_time_str = app_time.strftime('%H:%M')
            
            # Проверяем точное совпадение времени
            if app_time_str == selected_time:
                await callback.answer("Это время уже занято записью!")
                return
                
            if app.status == "CONFIRMED":
                next_hour = app_time + timedelta(hours=1)
                next_hour_str = next_hour.strftime('%H:%M')
                
                # Проверяем, не попадает ли новый слот в следующий час после подтвержденной записи
                if next_hour_str == selected_time:
                    await callback.answer("Это время занято (следующий час после подтвержденной записи)!")
                    return
                    
                # Проверяем, не попадает ли следующий час нового слота на подтвержденную запись
                new_slot_next_hour = slot_datetime + timedelta(hours=1)
                if new_slot_next_hour.strftime('%H:%M') == app_time_str:
                    await callback.answer("Невозможно создать слот - следующий час конфликтует с существующей записью!")
                    return

        # Создаем временной слот
        time_slot = TimeSlot(
            date=slot_datetime,
            is_available=True
        )
        session.add(time_slot)
        await session.commit()

        await callback.answer("✅ Слот успешно создан!")

        # Возвращаемся к просмотру слотов на дату
        text, keyboard = await get_time_slots_view(date, session)
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
            
    except Exception as e:
        logger.error(f"Ошибка при выборе времени: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при создании слота")
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при создании временного слота</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("select_time_slot_"), is_time_slots_callback)
async def handle_time_slot_selection(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обработка выбора существующего временного слота
    """
    try:
        slot_id = int(callback.data.split("_")[3])
        
        # Получаем слот
        slot = await session.get(TimeSlot, slot_id)
        if not slot:
            await callback.answer("Слот не найден!")
            return
            
        # Проверяем, есть ли записи на этот слот
        result = await session.execute(
            select(Appointment)
            .where(
                Appointment.time_slot_id == slot_id,
                Appointment.status.in_(["PENDING", "CONFIRMED"])
            )
        )
        appointment = result.scalar_one_or_none()
        
        if appointment:
            await callback.answer("Этот слот уже занят!")
            return
            
        # Если слот свободен
        await callback.answer(
            "✅ Слот свободен и доступен для записи",
            show_alert=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка при выборе слота: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при проверке слота")

@router.callback_query(F.data == "manual_time_schedule", is_time_slots_callback)
async def request_manual_time(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос ручного ввода времени
    """
    try:
        # Получаем дату из состояния
        data = await state.get_data()
        date_str = data.get("date")
        
        keyboard = [[InlineKeyboardButton(
            text="↩️ Назад к выбору времени",
            callback_data=f"add_slot_to_date_{date_str}"
        )]]
        
        await callback.message.edit_text(
            "<b>🕐 Введите время в одном из форматов:</b>\n"
            "• <code>ЧЧ</code> (10)\n"
            "• <code>ЧЧ:ММ</code> (10:30)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при запросе ручного ввода времени: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(lambda c: c.data.startswith("delete_slot_"), admin_filter, is_time_slots_callback)
async def delete_time_slot(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Удаление временного слота
    """
    try:
        slot_id = int(callback.data.split("_")[2])
        
        # Получаем слот с предзагрузкой связанных записей
        result = await session.execute(
            select(TimeSlot)
            .options(selectinload(TimeSlot.appointments))
            .where(TimeSlot.id == slot_id)
        )
        slot = result.scalar_one_or_none()
        
        if not slot:
            await callback.answer("Слот не найден!")
            return

        date_str = slot.date.strftime('%d.%m.%Y')
        
        # Проверяем наличие активных записей на этот слот
        active_appointments = [app for app in slot.appointments 
                             if app.status in ("PENDING", "CONFIRMED")]
        
        if active_appointments:
            await callback.answer(
                "❌ Невозможно удалить слот с активными записями!",
                show_alert=True
            )
            return
            
        # Сначала удаляем все связанные отмененные записи
        for app in slot.appointments:
            await session.delete(app)
            
        # Затем удаляем сам слот
        await session.delete(slot)
        await session.commit()
        
        await callback.answer("✅ Слот удален!")
        
        # Получаем обновленные слоты для этой даты
        text, keyboard = await get_time_slots_view(slot.date, session)
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в delete_time_slot: {e}", exc_info=True)
        await session.rollback()
        await callback.answer("❌ Произошла ошибка при удалении слота")
        await callback.message.edit_text(
            "Произошла ошибка при удалении слота",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data == "auto_create_slots_schedule", F.from_user.id.in_(settings.admin_ids), is_time_slots_callback)
async def start_auto_create_slots(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начало процесса автоматического создания слотов
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} начал процесс автосоздания слотов")
        
        # Устанавливаем состояние
        await state.set_state(TimeSlotStates.selecting_auto_month)
        
        # Создаем клавиатуру с выбором месяцев
        keyboard = []
        current_date = datetime.now()
        
        # Показываем текущий и следующие 2 месяца
        for i in range(3):
            if i == 0:
                future_date = current_date
            else:
                year = current_date.year + ((current_date.month + i - 1) // 12)
                month = ((current_date.month + i - 1) % 12) + 1
                future_date = datetime(year, month, 1)
            
            month_names = {
                1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
                5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
                9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
            }
            month_name = month_names[future_date.month]
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{month_name} {future_date.year}",
                    callback_data=f"auto_month_{future_date.strftime('%m.%Y')}"
                )
            ])
        
        # Добавляем кнопку "Назад"
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад к расписанию",
                callback_data="manage_schedule"
            )
        ])
        
        await callback.message.edit_text(
            "📅 Выберите месяц для автоматического создания слотов:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
        await callback.answer()
        
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "❌ Произошла ошибка при выборе месяца",
            reply_markup=get_admin_inline_keyboard()
        )

@router.callback_query(F.data.startswith("auto_month_"), TimeSlotStates.selecting_auto_month, is_time_slots_callback)
async def process_auto_month(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка выбора месяца для автосоздания слотов
    """
    try:
        month_year = callback.data.split("_")[2]
        month, year = map(int, month_year.split("."))
        logger.info(f"Администратор {callback.from_user.id} выбрал месяц {month}.{year} для автосоздания")
        
        # Отвечаем на callback до начала создания слотов
        await callback.answer("⏳ Создаю слоты...")
        
        # Определяем начало и конец месяца
        current_datetime = datetime.now().replace(second=0, microsecond=0)
        start_date = max(
            current_datetime.date(),
            datetime(year, month, 1).date()
        )
        
        # Определяем последний день месяца
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        end_date = (next_month - timedelta(days=1)).date()
        
        # Получаем все существующие слоты для выбранного месяца заранее
        existing_slots = await session.execute(
            select(TimeSlot)
            .where(
                TimeSlot.date >= datetime.combine(start_date, time.min),
                TimeSlot.date <= datetime.combine(end_date, time.max)
            )
        )
        existing_slots_set = {
            slot.date.strftime('%Y-%m-%d %H:%M')
            for slot in existing_slots.scalars().all()
        }
        
        slots_to_create = []
        current_date = start_date
        
        # Временное сообщение о процессе
        await callback.message.edit_text(
            f"⏳ Создаю слоты на {month}.{year}...\n"
            "Пожалуйста, подождите..."
        )
        
        while current_date <= end_date:
            # Пропускаем воскресенье (6 - это воскресенье)
            if current_date.weekday() == 6:
                current_date += timedelta(days=1)
                continue
            
            # Определяем расписание в зависимости от дня недели
            if current_date.weekday() < 5:  # ПН-ПТ
                time_ranges = [(9, 17)]  # с 9:00 до 17:00
            else:  # СБ
                time_ranges = [(10, 13)]  # с 10:00 до 13:00
            
            for start_hour, end_hour in time_ranges:
                for hour in range(start_hour, end_hour):
                    slot_datetime = datetime.combine(current_date, time(hour, 0))
                    
                    # Пропускаем слоты в прошлом
                    if slot_datetime <= current_datetime:
                        continue
                    
                    # Проверяем существование слота в предварительно загруженном наборе
                    slot_key = slot_datetime.strftime('%Y-%m-%d %H:%M')
                    if slot_key in existing_slots_set:
                        continue
                    
                    # Создаем новый слот
                    time_slot = TimeSlot(
                        date=slot_datetime,
                        is_available=True,
                        created_at=current_datetime,
                        updated_at=current_datetime
                    )
                    slots_to_create.append(time_slot)
            
            current_date += timedelta(days=1)
        
        # Сохраняем все созданные слоты одним запросом
        if slots_to_create:
            session.add_all(slots_to_create)
            await session.commit()
            logger.info(f"Создано {len(slots_to_create)} новых слотов на {month}.{year}")
        
        # Очищаем состояние
        await state.clear()
        
        # Получаем обновленный список слотов
        time_slots = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date >= current_datetime)
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        # Создаем клавиатуру с кнопками управления
        keyboard = [
            [InlineKeyboardButton(
                text="🔄 Автосоздание слотов на месяц",
                callback_data="auto_create_slots_schedule"
            )],
            [InlineKeyboardButton(
                text="➕ Добавить слот",
                callback_data="add_time_slot_schedule"
            )]
        ]
        
        # Получаем клавиатуру с датами
        dates_keyboard = get_time_slots_dates_keyboard(time_slots)
        
        # Формируем сообщение с результатами
        month_names = {
            1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
            5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
            9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
        }
        month_name = month_names[month]
        
        message_text = (
            f"<b>✅ Автоматически создано {len(slots_to_create)} слотов на {month_name} {year}!</b>\n\n"
            "<b>🕐 Управление расписанием</b>\n"
            "Выберите действие или дату для просмотра временных слотов:"
        )
        
        # Обновляем сообщение с результатами
        try:
            await callback.message.edit_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=keyboard + dates_keyboard.inline_keyboard
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении сообщения: {str(e)}")
            # Если не удалось обновить сообщение, отправляем новое
            await callback.message.answer(
                message_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=keyboard + dates_keyboard.inline_keyboard
                ),
                parse_mode="HTML"
            )
            
    except Exception as e:
        log_error(e)
        logger.error(f"Ошибка при автосоздании слотов: {str(e)}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при автосоздании слотов</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("date_page_"), is_time_slots_callback)
async def handle_date_pagination(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Обработчик пагинации дат
    """
    try:
        page = int(callback.data.split("_")[2])
        logger.info(f"Администратор {callback.from_user.id} переключился на страницу {page}")
        await callback.answer()
        
        time_slots = await session.execute(
            select(TimeSlot)
            .where(TimeSlot.date >= datetime.now())
            .order_by(TimeSlot.date)
        )
        time_slots = time_slots.scalars().all()
        
        # Создаем клавиатуру с кнопками управления
        keyboard = [
            [InlineKeyboardButton(
                text="🔄 Автосоздание слотов на месяц",
                callback_data="auto_create_slots_schedule"
            )],
            [InlineKeyboardButton(
                text="➕ Добавить слот",
                callback_data="add_time_slot_schedule"
            )]
        ]
        
        dates_keyboard = get_time_slots_dates_keyboard(time_slots, page)
        
        await callback.message.edit_text(
            "<b>🕐 Управление расписанием</b>\n\n"
            "Выберите действие или дату для просмотра временных слотов:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=keyboard + dates_keyboard.inline_keyboard
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при переключении страницы</b>",
            reply_markup=get_admin_inline_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("view_appointment_"), is_time_slots_callback)
async def view_appointment_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр деталей записи
    """
    try:
        appointment_id = int(callback.data.split("_")[2])
        
        # Получаем запись с предзагрузкой связанных данных
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена")
            return
            
        # Определяем статус и эмодзи
        status_emoji = "🕐" if appointment.status == "PENDING" else "🚗"
        status_text = "Ожидает подтверждения" if appointment.status == "PENDING" else "Подтверждена"
        
        # Формируем текст с информацией о записи
        text = (
            f"<b>📝 Информация о записи #{appointment.id}</b>\n\n"
            f"<b>Статус:</b> {status_emoji} {status_text}\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📱 Телефон:</b> {appointment.user.phone_number or 'Не указан'}\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n"
            f"<b>🚗 Автомобиль:</b> {appointment.car_brand} {appointment.car_model} ({appointment.car_year})\n"
        )
        
        if appointment.final_price:
            text += f"<b>💰 Стоимость:</b> {appointment.final_price}₽\n"
        else:
            text += f"<b>💰 Предварительная стоимость:</b> от {appointment.service.price}₽\n"
            
        if appointment.client_comment:
            text += f"\n<b>💬 Комментарий клиента:</b> {appointment.client_comment}\n"
        if appointment.admin_response:
            text += f"<b>↪️ Ответ администратора:</b> {appointment.admin_response}\n"
        if appointment.admin_comment:
            text += f"<b>👨‍💼 Комментарий для администраторов:</b> {appointment.admin_comment}\n"
            
        # Создаем клавиатуру с действиями
        keyboard = []
        
        # Кнопки в зависимости от статуса
        if appointment.status == "PENDING":
            keyboard.append([
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_appointment_{appointment.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_appointment_{appointment.id}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_appointment_{appointment.id}"
                )
            ])
            
        # Добавляем кнопку для комментария
        keyboard.append([
            InlineKeyboardButton(
                text="💬 Добавить комментарий",
                callback_data=f"add_appointment_comment_{appointment.id}"
            )
        ])
        
        # Кнопка возврата
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад к расписанию",
                callback_data=f"view_date_{appointment.time_slot.date.strftime('%d.%m.%Y')}"
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей записи: {e}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при загрузке информации о записи</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Назад", callback_data="manage_schedule")
            ]]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("add_appointment_comment_"), is_time_slots_callback)
async def start_add_appointment_comment(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса добавления комментария к записи
    """
    try:
        appointment_id = int(callback.data.split("_")[3])
        
        # Проверяем и очищаем состояния
        await check_and_clear_states(state)
        
        # Получаем запись
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            ))
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена")
            return
            
        # Сохраняем ID записи и источник в состояние
        await state.update_data(
            appointment_id=appointment_id,
            source='schedule' if 'view_date_' in callback.message.text else 'appointments'
        )
        await state.set_state(TimeSlotStates.adding_comment)
        
        # Показываем текущий комментарий, если есть
        text = (
            f"<b>💬 Добавление комментария к записи #{appointment.id}</b>\n\n"
            f"<b>👤 Клиент:</b> {appointment.user.full_name}\n"
            f"<b>📅 Дата:</b> {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>💇‍♂️ Услуга:</b> {appointment.service.name}\n\n"
        )
        
        if appointment.admin_comment:
            text += f"<b>Текущий комментарий:</b>\n{appointment.admin_comment}\n\n"
            
        text += "<b>Введите новый комментарий:</b>"
        
        # Добавляем кнопку отмены
        keyboard = [[
            InlineKeyboardButton(
                text="↩️ Отмена",
                callback_data=f"view_appointment_{appointment.id}"
            )
        ]]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале добавления комментария: {e}", exc_info=True)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при добавлении комментария</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Назад", callback_data="manage_schedule")
            ]]),
            parse_mode="HTML"
        )

@router.message(TimeSlotStates.adding_comment)
async def process_appointment_comment(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка ввода комментария к записи
    """
    try:
        data = await state.get_data()
        appointment_id = data.get('appointment_id')
        source = data.get('source', 'appointments')
        
        if not appointment_id:
            await message.answer(
                "<b>❌ Произошла ошибка. Начните процесс добавления комментария заново.</b>",
                parse_mode="HTML"
            )
            await state.clear()
            return
            
        # Получаем запись
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await message.answer(
                "<b>❌ Запись не найдена</b>",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Сохраняем комментарий
        appointment.admin_comment = message.text
        await session.commit()
        
        # Очищаем состояние
        await state.clear()
        
        # Формируем компактное сообщение с деталями записи
        status_emoji = "✅" if appointment.status == "CONFIRMED" else "🕐"
        price_text = f"{appointment.final_price}₽" if appointment.final_price else f"от {appointment.service.price}₽"
        
        text = (
            f"<b>{status_emoji} Запись #{appointment.id}</b>\n"
            f"<b>⏰ {appointment.time_slot.date.strftime('%H:%M')} "
            f"📅 {appointment.time_slot.date.strftime('%d.%m.%Y')}</b>\n"
            f"<b>👤</b> {appointment.user.full_name}\n"
            f"<b>📱</b> {appointment.user.phone_number or 'Нет телефона'}\n"
            f"<b>🚘</b> {appointment.car_brand} {appointment.car_model} ({appointment.car_year})\n"
            f"<b>💇‍♂️</b> {appointment.service.name}\n"
            f"<b>💰</b> {price_text}\n"
        )
        
        # Добавляем комментарии в компактном виде
        if appointment.client_comment:
            text += f"<b>💬 Клиент:</b> {appointment.client_comment}\n"
        if appointment.admin_response:
            text += f"<b>↪️ Ответ:</b> {appointment.admin_response}\n"
        if appointment.admin_comment:
            text += f"<b>👨‍💼 Для админов:</b> {appointment.admin_comment}\n"
            
        # Создаем компактную клавиатуру
        keyboard = []
        
        # Первый ряд: основные действия
        row1 = []
        if appointment.status != "CONFIRMED":
            row1.append(InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"confirm_appointment_{appointment.id}"
            ))
        row1.append(InlineKeyboardButton(
            text="❌ Отменить",
            callback_data=f"cancel_appointment_{appointment.id}"
        ))
        keyboard.append(row1)
        
        # Второй ряд: дополнительные действия
        keyboard.append([
            InlineKeyboardButton(
                text="💬 Комментарий",
                callback_data=f"add_appointment_comment_{appointment.id}"
            )
        ])
        
        # Третий ряд: кнопка возврата
        back_text = "↩️ К расписанию" if source == 'schedule' else "↩️ К записям"
        back_data = (f"view_date_{appointment.time_slot.date.strftime('%d.%m.%Y')}" 
                    if source == 'schedule' else "view_week_appointments")
        keyboard.append([
            InlineKeyboardButton(text=back_text, callback_data=back_data)
        ])
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении комментария: {e}", exc_info=True)
        await message.answer(
            "<b>❌ Произошла ошибка при сохранении комментария</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Назад", callback_data="manage_schedule")
            ]]),
            parse_mode="HTML"
        )
        await state.clear()
# src/handlers/client/profile.py

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from database.models import User, Appointment, Service, TimeSlot
from keyboards.client.client import get_profile_keyboard, get_main_keyboard, get_contact_keyboard
from states.client import ProfileStates, ClientStates
from core.utils import log_error
from config.settings import settings
from handlers.admin.appointments import STATUS_TRANSLATIONS
from handlers.admin.appointments import bot
from core.utils.time_slots import update_completed_appointments

router = Router()


@router.message(F.text == "👤 Личный кабинет")
async def show_profile(message: Message, session: AsyncSession, user: User) -> None:
    """
    Показывает профиль пользователя
    """
    # Обновляем статусы записей
    await update_completed_appointments(session)

    # Проверяем наличие активных записей
    result = await session.execute(
        select(Appointment)
        .join(TimeSlot)
        .where(
            Appointment.user_id == user.id,
            Appointment.status.in_(["PENDING", "CONFIRMED"]),
            TimeSlot.date >= datetime.now()
        )
        .order_by(TimeSlot.date)
        .options(
            selectinload(Appointment.time_slot)
        )
    )
    active_appointments = result.scalars().all()

    text = (
        f"👤 Профиль\n\n"
        f"Имя: {user.full_name}\n"
        f"Телефон: {user.phone_number or 'Не указан'}\n"
    )

    if active_appointments:
        text += "\n🎯 Ваши активные записи:\n"
        for app in active_appointments:
            text += f"• {app.time_slot.date.strftime('%d.%m %H:%M')} (#{app.id})\n"

    text += "\nВыберите действие:"
    
    keyboard = []
    
    # Добавляем кнопку активных записей только если они есть
    if active_appointments:
        keyboard.append([InlineKeyboardButton(text="🎯 Активные записи", callback_data="view_active_appointments")])
    
    keyboard.extend([
        [InlineKeyboardButton(text="📋 История записей", callback_data="view_history")],
        [InlineKeyboardButton(text="📱 Изменить телефон", callback_data="change_phone")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
    ])
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.message(F.text == "📱 Изменить контакт")
async def start_change_contact(message: Message, state: FSMContext) -> None:
    """
    Начало процесса изменения контактных данных
    """
    await state.set_state(ProfileStates.changing_contact)
    await message.answer(
        "Пожалуйста, поделитесь своим новым номером телефона",
        reply_markup=get_contact_keyboard()
    )


@router.message(ProfileStates.changing_contact, F.content_type.in_({'contact'}))
async def handle_contact_update(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    """
    Обработчик получения контакта при изменении номера
    """
    try:
        logger.info("Получен контакт для обновления")
        
        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(
                "Пожалуйста, отправьте свой контакт",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="📱 Отправить контакт", request_contact=True)],
                        [KeyboardButton(text="❌ Отмена")]
                    ],
                    resize_keyboard=True
                )
            )
            return

        # Обновляем номер
        user.phone_number = message.contact.phone_number
        await session.commit()
        logger.info(f"Номер обновлен на {user.phone_number}")

        # Очищаем состояние
        await state.clear()

        # Отправляем подтверждение
        await message.answer(
            "✅ Номер телефона успешно обновлен!",
            reply_markup=get_main_keyboard()
        )

        # Показываем обновленный профиль
        await show_profile(message, session, user)

    except Exception as e:
        logger.error(f"Ошибка при обновлении контакта: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обновлении номера",
            reply_markup=get_main_keyboard()
        )
        await state.clear()


@router.message(ProfileStates.changing_contact)
async def handle_wrong_contact_input(message: Message) -> None:
    """
    Обработчик неверного ввода при изменении контакта
    """
    await message.answer(
        "Пожалуйста, используйте кнопку 'Отправить контакт' или нажмите 'Отмена'",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Отправить контакт", request_contact=True)],
                [KeyboardButton(text="❌ Отмена")]
            ],
            resize_keyboard=True
        )
    )


@router.message(F.text == "📋 История записей")
async def show_history(message: Message, session: AsyncSession, user: User) -> None:
    """
    Показывает историю записей пользователя с возможностью отмены активных записей
    """
    appointments = await session.execute(
        select(Appointment)
        .join(TimeSlot)
        .where(Appointment.user_id == user.id)
        .order_by(TimeSlot.date.desc())
        .options(
            selectinload(Appointment.service),
            selectinload(Appointment.time_slot)
        )
    )
    appointments = appointments.scalars().all()

    if not appointments:
        await message.answer(
            "У вас пока нет записей в истории.",
            reply_markup=get_main_keyboard()
        )
        return

    active_appointments = [app for app in appointments if app.status in ["PENDING", "CONFIRMED"]]
    past_appointments = [app for app in appointments if app.status not in ["PENDING", "CONFIRMED"]]

    text = "📋 Ваши записи:\n\n"
    keyboard = []

    if active_appointments:
        text += "🟢 Активные записи:\n\n"
        for app in active_appointments:
            status_emoji = "🕐" if app.status == "PENDING" else "✅"
            price_info = f"💰 Стоимость: {app.final_price}₽" if app.final_price else f"💰 Предварительная стоимость: от {app.service.price}₽"
            
            text += (
                f"{status_emoji} Запись #{app.id}\n"
                f"📅 Дата: {app.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
                f"💇‍♂️ Услуга: {app.service.name}\n"
                f"{price_info}\n"
                f"📊 Статус: {STATUS_TRANSLATIONS[app.status]}\n\n"
            )
            
            # Добавляем кнопку отмены только для записей, которые можно отменить
            keyboard.append([InlineKeyboardButton(
                text=f"❌ Отменить запись #{app.id}",
                callback_data=f"client_cancel_appointment_{app.id}"
            )])

    if past_appointments:
        text += "\n📜 История записей:\n\n"
        for app in past_appointments[:5]:  # Показываем только последние 5 записей
            status_emoji = "✅" if app.status == "COMPLETED" else "❌"
            text += (
                f"{status_emoji} Запись #{app.id}\n"
                f"📅 Дата: {app.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
                f"💇‍♂️ Услуга: {app.service.name}\n"
                f"📊 Статус: {STATUS_TRANSLATIONS[app.status]}\n"
                "-------------------\n"
            )

    # Добавляем кнопку возврата в главное меню
    keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else get_main_keyboard()
    )

def get_russian_month_name(month: int) -> str:
    """
    Возвращает название месяца на русском языке
    """
    months = {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь"
    }
    return months.get(month, "")

def escape_markdown_v2(text: str) -> str:
    """
    Экранирует специальные символы для Markdown V2
    """
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars:
        text = text.replace(char, f"\\{char}")
    return text

@router.callback_query(F.data == "view_history")
async def handle_view_history(callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    """
    Обработчик для просмотра истории записей через callback
    """
    try:
        await callback.answer()
        
        # Получаем все записи пользователя
        appointments = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(Appointment.user_id == user.id)
            .order_by(TimeSlot.date.desc())
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = appointments.scalars().all()

        if not appointments:
            # Удаляем предыдущее сообщение
            await callback.message.delete()
            await callback.message.answer(
                "У вас пока нет записей в истории.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_profile")
                ]])
            )
            return

        # Разделяем записи на активные и прошедшие
        active_appointments = [app for app in appointments if app.status in ["PENDING", "CONFIRMED"]]
        past_appointments = [app for app in appointments if app.status not in ["PENDING", "CONFIRMED"]]

        # Подсчет статистики
        total_appointments = len(appointments)
        completed_appointments = len([app for app in appointments if app.status == "COMPLETED"])
        cancelled_appointments = len([app for app in appointments if app.status == "CANCELLED"])
        total_spent = sum([app.final_price for app in appointments if app.final_price and app.status == "COMPLETED"])

        # Группируем прошедшие записи по месяцам
        past_appointments_by_month = {}
        for app in past_appointments:
            month_key = app.time_slot.date.strftime('%Y-%m')
            if month_key not in past_appointments_by_month:
                past_appointments_by_month[month_key] = []
            past_appointments_by_month[month_key].append(app)

        # Формируем текст со статистикой
        text = (
            "📊 *Ваша статистика:*\n"
            f"• Всего записей: {total_appointments}\n"
            f"• Завершено успешно: {completed_appointments}\n"
            f"• Отменено: {cancelled_appointments}\n"
            f"• Общая сумма: {total_spent}₽\n\n"
        )

        # Добавляем активные записи, если они есть
        if active_appointments:
            text += "*🟢 Активные записи:*\n\n"
            for app in active_appointments:
                status_emoji = "🕐" if app.status == "PENDING" else "✅"
                price_info = f"💰 {app.final_price}₽" if app.final_price else f"💰 от {app.service.price}₽"
                date_str = escape_markdown_v2(app.time_slot.date.strftime('%d.%m.%Y %H:%M'))
                
                text += (
                    f"{status_emoji} *Запись \\#{app.id}*\n"
                    f"📅 {date_str}\n"
                    f"💇‍♂️ {escape_markdown_v2(app.service.name)}\n"
                    f"{escape_markdown_v2(price_info)}\n"
                    f"📊 {escape_markdown_v2(STATUS_TRANSLATIONS[app.status])}\n\n"
                )

        # Создаем клавиатуру
        keyboard = []
        
        # Добавляем кнопки отмены для активных записей
        for app in active_appointments:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"❌ Отменить запись #{app.id}",
                    callback_data=f"client_cancel_appointment_{app.id}"
                )
            ])

        # Добавляем кнопки с месяцами для истории
        for month_key in past_appointments_by_month.keys():
            month_date = datetime.strptime(month_key, '%Y-%m')
            month_name = get_russian_month_name(month_date.month)
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📅 {month_name} {month_date.year}",
                    callback_data=f"history_month_{month_key}"
                )
            ])

        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_profile")
        ])

        # Удаляем предыдущее сообщение
        await callback.message.delete()

        # Отправляем новое сообщение
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        logger.error(f"Ошибка при показе истории: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при загрузке истории",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_profile")
            ]])
        )

def get_week_range(date: datetime) -> tuple[datetime, datetime]:
    """
    Возвращает начало и конец недели для заданной даты
    """
    start = date - timedelta(days=date.weekday())
    end = start + timedelta(days=6)
    return start, end

def get_week_number(date: datetime) -> int:
    """
    Возвращает номер недели в месяце (1-5)
    """
    return (date.day - 1) // 7 + 1

@router.callback_query(F.data.startswith("history_month_"))
async def show_month_history(callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    """
    Показывает историю записей за выбранный месяц
    """
    try:
        # Получаем параметры из callback_data
        parts = callback.data.split("_")
        month_key = parts[2]
        week = int(parts[3]) if len(parts) > 3 else 1  # Номер недели, по умолчанию 1
        
        # Если пользователь нажимает на текущую неделю (синюю кнопку), просто игнорируем
        if callback.message.reply_markup:
            for row in callback.message.reply_markup.inline_keyboard:
                for button in row:
                    if button.callback_data == callback.data and button.text.startswith("🔵"):
                        await callback.answer("Это текущая неделя")
                        return

        await callback.answer()
        
        month_date = datetime.strptime(month_key, '%Y-%m')
        
        # Получаем записи за выбранный месяц
        appointments = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                Appointment.user_id == user.id,
                TimeSlot.date >= month_date,
                TimeSlot.date < month_date + timedelta(days=32)
            )
            .order_by(TimeSlot.date.desc())
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = appointments.scalars().all()

        # Группируем записи по неделям
        appointments_by_week = {}
        for app in appointments:
            week_num = get_week_number(app.time_slot.date)
            if week_num not in appointments_by_week:
                appointments_by_week[week_num] = []
            appointments_by_week[week_num].append(app)

        month_name = get_russian_month_name(month_date.month)
        text = f"📅 *{escape_markdown_v2(month_name)} {month_date.year}*\n\n"
        
        # Статистика за месяц
        total_appointments = len(appointments)
        completed_appointments = len([app for app in appointments if app.status == "COMPLETED"])
        cancelled_appointments = len([app for app in appointments if app.status == "CANCELLED"])
        total_spent = sum([app.final_price for app in appointments if app.final_price and app.status == "COMPLETED"])

        text += (
            f"📊 *Статистика за месяц:*\n"
            f"• Всего записей: {total_appointments}\n"
            f"• Завершено успешно: {completed_appointments}\n"
            f"• Отменено: {cancelled_appointments}\n"
            f"• Общая сумма: {total_spent}₽\n\n"
        )

        # Добавляем записи текущей недели
        if week in appointments_by_week:
            start_date, end_date = get_week_range(next(iter(appointments_by_week[week])).time_slot.date)
            text += f"*📆 Неделя {week} \\({escape_markdown_v2(start_date.strftime('%d.%m'))} \\- {escape_markdown_v2(end_date.strftime('%d.%m'))}\\):*\n\n"
            
            for app in appointments_by_week[week]:
                status_emoji = get_status_emoji(app.status)
                price_info = f"💰 {app.final_price}₽" if app.final_price else f"💰 от {app.service.price}₽"
                date_str = escape_markdown_v2(app.time_slot.date.strftime('%d.%m.%Y %H:%M'))
                
                text += (
                    f"{status_emoji} *Запись \\#{app.id}*\n"
                    f"📅 {date_str}\n"
                    f"💇‍♂️ {escape_markdown_v2(app.service.name)}\n"
                    f"{escape_markdown_v2(price_info)}\n"
                    f"📊 {escape_markdown_v2(STATUS_TRANSLATIONS[app.status])}\n\n"
                )

        # Создаем клавиатуру с навигацией по неделям
        keyboard = []
        
        # Добавляем навигацию по неделям
        week_buttons = []
        for week_num in sorted(appointments_by_week.keys()):
            week_buttons.append(
                InlineKeyboardButton(
                    text=f"{'🔵' if week_num == week else '⚪️'} Неделя {week_num}",
                    callback_data=f"history_month_{month_key}_{week_num}"
                )
            )
            # Добавляем ряд после каждых двух кнопок
            if len(week_buttons) == 2:
                keyboard.append(week_buttons)
                week_buttons = []
        if week_buttons:  # Добавляем оставшиеся кнопки
            keyboard.append(week_buttons)

        # Добавляем кнопки навигации
        keyboard.extend([
            [InlineKeyboardButton(text="↩️ Назад к истории", callback_data="view_history")],
            [InlineKeyboardButton(text="🔙 В профиль", callback_data="back_to_profile")]
        ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        logger.error(f"Ошибка при показе истории за месяц: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке истории",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Назад", callback_data="view_history")
            ]])
        )

def get_status_emoji(status: str) -> str:
    """
    Возвращает эмодзи для статуса записи
    """
    status_emojis = {
        "PENDING": "🕐",
        "CONFIRMED": "✅",
        "COMPLETED": "✨",
        "CANCELLED": "❌",
        "EXPIRED": "⏰"
    }
    return status_emojis.get(status, "❓")

@router.callback_query(F.data == "change_phone")
async def handle_change_phone(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик для изменения телефона через callback
    """
    try:
        await callback.answer()
        await state.set_state(ProfileStates.changing_contact)
        
        # Создаем клавиатуру с двумя опциями
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Отправить контакт",
                    callback_data="send_contact"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Ввести вручную",
                    callback_data="enter_phone_manually"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="back_to_profile"
                )
            ]
        ])
        
        await callback.message.edit_text(
            "Выберите способ изменения номера телефона:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале изменения телефона: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(F.data == "send_contact")
async def request_contact(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос контакта через кнопку в клавиатуре
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить контакт", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    
    # Отправляем новое сообщение и сохраняем его ID
    message = await callback.message.answer(
        "Нажмите на кнопку 'Отправить контакт' ниже:",
        reply_markup=keyboard
    )
    
    # Сохраняем ID сообщения для последующего удаления
    await state.update_data(message_to_delete=message.message_id)
    
    # Удаляем сообщение с inline кнопками
    await callback.message.delete()

@router.callback_query(F.data == "enter_phone_manually")
async def request_manual_phone(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос ручного ввода номера телефона
    """
    await state.set_state(ProfileStates.entering_phone)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_profile")
    ]])
    
    await callback.message.edit_text(
        "Введите номер телефона в формате +7XXXXXXXXXX:",
        reply_markup=keyboard
    )

@router.message(ProfileStates.entering_phone)
async def process_manual_phone(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    """
    Обработка введенного вручную номера телефона
    """
    phone = message.text.strip()
    
    # Простая валидация номера
    if not (phone.startswith('+7') and len(phone) == 12 and phone[1:].isdigit()):
        await message.answer(
            "❌ Неверный формат номера. Введите номер в формате +7XXXXXXXXXX:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_profile")
            ]])
        )
        return
    
    # Обновляем номер телефона
    user.phone_number = phone
    await session.commit()
    
    await state.clear()
    await message.answer(
        "✅ Номер телефона успешно обновлен!",
        reply_markup=get_main_keyboard()
    )
    await show_profile(message, session, user)

@router.message(F.text == "❌ Отмена", ProfileStates.changing_contact)
@router.message(F.text == "❌ Отмена", ProfileStates.entering_phone)
async def cancel_phone_change(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    """
    Отмена изменения номера телефона
    """
    await state.clear()
    await message.answer(
        "Изменение номера отменено",
        reply_markup=get_main_keyboard()
    )
    await show_profile(message, session, user)

@router.callback_query(F.data == "view_active_appointments")
async def show_active_appointments(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    """
    Показывает все активные записи пользователя
    """
    try:
        # Получаем все активные записи
        result = await session.execute(
            select(Appointment)
            .join(TimeSlot)
            .where(
                Appointment.user_id == user.id,
                Appointment.status.in_(["PENDING", "CONFIRMED"]),
                TimeSlot.date >= datetime.now()
            )
            .order_by(TimeSlot.date)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointments = result.scalars().all()
        
        if not appointments:
            await callback.message.edit_text(
                "У вас нет активных записей",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_profile")
                ]])
            )
            return

        text = "🎯 Ваши активные записи:\n\n"
        keyboard = []
        
        for appointment in appointments:
            status_emoji = "✅" if appointment.status == "CONFIRMED" else "🕐"
            price_text = f"{appointment.final_price}₽" if appointment.final_price else f"от {appointment.service.price}₽"
            
            text += (
                f"{status_emoji} Запись #{appointment.id}\n"
                f"📅 Дата: {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
                f"💇‍♂️ Услуга: {appointment.service.name}\n"
                f"💰 Стоимость: {price_text}\n"
                f"📊 Статус: {STATUS_TRANSLATIONS[appointment.status]}\n\n"
            )
            
            # Добавляем кнопку отмены только для записей, которые можно отменить
            if appointment.status in ["PENDING", "CONFIRMED"]:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"❌ Отменить запись #{appointment.id}",
                        callback_data=f"client_cancel_appointment_{appointment.id}"
                    )
                ])

        keyboard.append([
            InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_profile")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе активных записей: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при загрузке записей")

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    """
    Возврат в профиль
    """
    await callback.message.delete()
    await callback.answer()
    await show_profile(callback.message, session, user)

@router.callback_query(F.data.startswith("dont_cancel_"))
async def cancel_cancellation(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Отмена процесса отмены записи
    """
    try:
        # Очищаем состояние
        await state.clear()
        
        # Получаем ID записи
        appointment_id = int(callback.data.split("_")[2])
        
        # Получаем запись для отображения информации
        result = await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.time_slot)
            )
        )
        appointment = result.scalar_one_or_none()
        
        if not appointment:
            await callback.answer("Запись не найдена")
            return
            
        # Возвращаем пользователя к информации о записи
        status_emoji = "✅" if appointment.status == "CONFIRMED" else "🕐"
        price_text = f"{appointment.final_price}₽" if appointment.final_price else f"от {appointment.service.price}₽"
        
        text = (
            f"{status_emoji} Запись #{appointment.id}\n"
            f"📅 Дата: {appointment.time_slot.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"💇‍♂️ Услуга: {appointment.service.name}\n"
            f"💰 Стоимость: {price_text}\n"
            f"📊 Статус: {STATUS_TRANSLATIONS[appointment.status]}"
        )
        
        keyboard = [
            [InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data=f"client_cancel_appointment_{appointment.id}"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="back_to_profile"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отмене отмены записи: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")
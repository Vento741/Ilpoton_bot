# src/handlers/admin/price_requests.py

from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger


from database.models import PriceRequest, User
from states.admin import PriceRequestStates

router = Router(name='admin_price_requests')

# Добавим в начало файла константы с шаблонами
RESPONSE_TEMPLATES = {
    "base": (
        "Здравствуйте!\n"
        "Стоимость {service_name} для {car_info} составит {price}₽.\n"
        "Записаться можно через кнопку ниже."
    ),
    "range": (
        "Здравствуйте!\n"
        "Стоимость {service_name} для {car_info} составит от {min_price}₽ до {max_price}₽.\n"
        "Точную стоимость сможем назвать после осмотра автомобиля.\n"
        "Записаться можно через кнопку ниже."
    ),
    "complex": (
        "Здравствуйте!\n"
        "Для точного расчета стоимости {service_name} нужен осмотр автомобиля.\n"
        "Запишитесь на бесплатную консультацию, и мы сделаем точный расчет на месте."
    )
}

# В начале price_requests.py добавим список префиксов
PRICE_REQUEST_PREFIXES = [
    "manage_price_requests",
    "respond_price_",
    "template_",
    "custom_response_",
    "archive_price_",
    "edit_price_response_",
    "price_request_details_",
    "confirm_archive_",
    "send_prepared_response_",
    "edit_prepared_response_",
    "filter_pending_requests",
    "filter_answered_requests",
    "archived_price_requests",
    "archived_page_"
]

def is_price_request_callback(callback: CallbackQuery) -> bool:
    """
    Проверяет, относится ли callback к управлению запросами на расчет стоимости
    """
    return any(callback.data.startswith(prefix) for prefix in PRICE_REQUEST_PREFIXES)

@router.callback_query(F.data == "manage_price_requests", is_price_request_callback)
async def show_price_requests(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает статистику и меню управления запросами
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} открыл управление запросами")
        await callback.answer()
        
        # Получаем количество запросов по статусам
        pending_result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.status == "PENDING")
        )
        pending_count = len(pending_result.scalars().all())
        
        answered_result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.status == "ANSWERED")
        )
        answered_count = len(answered_result.scalars().all())
        
        archived_result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.status == "ARCHIVED")
        )
        archived_count = len(archived_result.scalars().all())
        
        # Формируем текст со статистикой
        text = (
            "<b>📊 Статистика запросов на расчет стоимости:</b>\n\n"
            f"<b>🕐 Ожидают ответа:</b> {pending_count}\n"
            f"<b>✅ Отвеченные:</b> {answered_count}\n" 
            f"<b>📦 В архиве:</b> {archived_count}\n"
            f"<b>📝 Всего запросов:</b> {pending_count + answered_count + archived_count}\n\n"
            "<i>Выберите категорию для просмотра:</i>"
        )
        
        # Создаем упрощенное меню
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"🕐 Ожидающие ({pending_count})",
                    callback_data="filter_pending_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"✅ Отвеченные ({answered_count})",
                    callback_data="filter_answered_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📦 Архив ({archived_count})",
                    callback_data="archived_price_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="back_to_admin"
                )
            ]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в show_price_requests: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке статистики запросов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Назад в меню",
                    callback_data="back_to_admin"
                )
            ]]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("respond_price_"), is_price_request_callback)
async def start_price_response(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса ответа на запрос
    """
    try:
        request_id = int(callback.data.split("_")[2])
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
        
        # Сохраняем ID запроса в состояние
        await state.update_data(request_id=request_id)
        
        # Создаем клавиатуру с шаблонами и отменой
        keyboard = [
            [
                InlineKeyboardButton(
                    text="💰 Точная цена",
                    callback_data=f"template_base_{request_id}"
                ),
                InlineKeyboardButton(
                    text="📊 Диапазон цен",
                    callback_data=f"template_range_{request_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Нужен осмотр",
                    callback_data=f"template_complex_{request_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Свой ответ",
                    callback_data=f"custom_response_{request_id}"
                )
            ],
            [
                InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="manage_price_requests"
                )
            ]
        ]
        
        text = (
            f"<b>💬 Ответ на запрос цены #{request_id}</b>\n\n"
            f"<b>👤 Клиент:</b> {request.user.full_name}\n"
            f"<b>🔧 Услуга:</b> {request.service.name}\n"
            f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
            "<b>Выберите шаблон ответа или напишите свой:</b>"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале ответа: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(F.data.startswith("template_"), is_price_request_callback)
async def use_response_template(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Использование шаблона ответа
    """
    try:
        template_type, request_id = callback.data.split("_")[1:3]
        request_id = int(request_id)
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
            
        # Устанавливаем состояние для ожидания параметров шаблона
        await state.update_data(
            request_id=request_id,
            template_type=template_type
        )
        await state.set_state(PriceRequestStates.waiting_for_template_params)
        
        # Запрашиваем параметры в зависимости от шаблона
        if template_type == "base":
            text = "<b>Введите стоимость услуги (только число):</b>"
        elif template_type == "range":
            text = "<b>Введите минимальную и максимальную стоимость через пробел (например: 5000 7000):</b>"
        else:  # complex
            # Для сложного шаблона параметры не нужны
            await process_template_response(callback, state, session, None)
            return
            
        keyboard = [[
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"respond_price_{request_id}"
            )
        ]]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при использовании шаблона: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.message(
    PriceRequestStates.waiting_for_template_params,
    F.text.regexp(r'^\d+(?:\s+\d+)?$')  # Проверяем, что текст содержит одно или два числа
)
async def process_template_params(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка параметров шаблона
    """
    try:
        data = await state.get_data()
        template_type = data.get("template_type")
        
        if template_type == "base":
            try:
                price = int(message.text.strip())
                if price <= 0:
                    await message.answer("❌ Цена должна быть положительным числом", parse_mode="HTML")
                    return
                await process_template_response(message, state, session, {"price": price})
            except ValueError:
                await message.answer("❌ Пожалуйста, введите только число", parse_mode="HTML")
                return
                
        elif template_type == "range":
            try:
                min_price, max_price = map(int, message.text.strip().split())
                if min_price <= 0 or max_price <= 0:
                    await message.answer("❌ Цены должны быть положительными числами", parse_mode="HTML")
                    return
                if min_price >= max_price:
                    await message.answer("❌ Минимальная цена должна быть меньше максимальной", parse_mode="HTML")
                    return
                await process_template_response(
                    message, 
                    state, 
                    session, 
                    {"min_price": min_price, "max_price": max_price}
                )
            except ValueError:
                await message.answer(
                    "❌ Пожалуйста, введите два числа через пробел\n"
                    "Например: 5000 7000",
                    parse_mode="HTML"
                )
                return
                
    except Exception as e:
        logger.error(f"Ошибка при обработке параметров шаблона: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обработке параметров",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                callback_data="manage_price_requests"
                )
            ]]),
            parse_mode="HTML"
        )
        await state.clear()

# Добавим обработчик для некорректного ввода
@router.message(PriceRequestStates.waiting_for_template_params)
async def process_invalid_template_params(message: Message, state: FSMContext) -> None:
    """
    Обработка некорректного ввода параметров шаблона
    """
    data = await state.get_data()
    template_type = data.get("template_type")
    
    if template_type == "base":
        await message.answer(
            "❌ Пожалуйста, введите только число\n"
            "Например: 5000",
            parse_mode="HTML"
        )
    elif template_type == "range":
        await message.answer(
            "❌ Пожалуйста, введите два числа через пробел\n"
            "Например: 5000 7000",
            parse_mode="HTML"
        )

async def process_template_response(event, state: FSMContext, session: AsyncSession, params: dict = None) -> None:
    """
    Обработка ответа по шаблону
    """
    try:
        data = await state.get_data()
        request_id = data.get("request_id")
        template_type = data.get("template_type")
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await event.answer("❌ Запрос не найден")
            await state.clear()
            return
            
        # Формируем ответ по шаблону
        template = RESPONSE_TEMPLATES[template_type]
        template_params = {
            "service_name": request.service.name,
            "car_info": request.car_info
        }
        if params:
            template_params.update(params)
            
        response_text = template.format(**template_params)
        
        # Создаем новое сообщение с готовым ответом
        data = await state.update_data(prepared_response=response_text)
        await state.set_state(PriceRequestStates.waiting_for_response)
        
        keyboard = [[
            InlineKeyboardButton(
                text="✅ Отправить",
                callback_data=f"send_prepared_response_{request_id}"
            ),
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"edit_prepared_response_{request_id}"
            )
        ]]
        
        text = (
            f"📝 Подготовленный ответ на запрос цены #{request_id}:\n\n"
            f"{response_text}\n\n"
            "Отправить или отредактировать?"
        )
        
        if isinstance(event, Message):
            await event.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
        else:  # CallbackQuery
            await event.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке шаблона: {e}", exc_info=True)
        if isinstance(event, Message):
            await event.answer("Произошла ошибка", parse_mode="HTML")
        else:
            await event.answer("Произошла ошибка", show_alert=True)
        await state.clear()

@router.message(PriceRequestStates.waiting_for_response)
async def process_price_response(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка ответа администратора (нового или редактирования)
    """
    try:
        data = await state.get_data()
        request_id = data.get("request_id")
        is_editing = data.get("is_editing", False)
        
        # Получаем запрос
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await message.answer("❌ Запрос не найден", parse_mode="HTML")
            await state.clear()
            return
        
        # Получаем или создаем администратора
        admin = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        admin = admin.scalar_one_or_none()
        
        if not admin:
            admin = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                is_admin=True
            )
            session.add(admin)
            await session.flush()
        
        # Обновляем запрос
        request.admin_response = message.text.strip()
        request.admin_id = admin.id
        request.status = "ANSWERED"
        
        if not is_editing:
            request.answered_at = datetime.now()
        
        await session.commit()
        
        # Проверяем, не является ли пользователь ботом
        is_user_bot = False
        if request.user.username and request.user.username.lower().endswith('bot'):
            is_user_bot = True
            logger.warning(f"Пользователь {request.user.telegram_id} ({request.user.username}) похож на бота. Сообщение не будет отправлено.")
        
        # Отправляем уведомление клиенту только если он не бот
        notification_sent = False
        if not is_user_bot:
            try:
                text = (
                    f"<b>💰 {'Обновлён расчет' if is_editing else 'Расчет'} стоимости по вашему запросу:</b>\n\n"
                    f"<b>🔧 Услуга:</b> {request.service.name}\n"
                    f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
                    f"<b>💬 Ответ менеджера:</b>\n{request.admin_response}"
                )
                
                await bot.send_message(
                    request.user.telegram_id,
                    text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="📝 Записаться",
                            callback_data=f"book_from_price_request_{request.service_id}_{request_id}"
                        )
                    ]]),
                    parse_mode="HTML"
                )
                notification_sent = True
            except Exception as e:
                logger.error(f"Не удалось отправить ответ клиенту: {e}")
        
        # Отправляем подтверждение администратору
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Архивировать",
                    callback_data=f"archive_price_{request_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"edit_price_response_{request_id}"
                )
            ],
            [InlineKeyboardButton(
                text="↩️ К списку запросов",
                callback_data="manage_price_requests"
            )]
        ])
        
        status_text = ""
        if is_user_bot:
            status_text = "⚠️ Ответ сохранен, но не отправлен (пользователь похож на бота)"
        elif not notification_sent:
            status_text = "⚠️ Ответ сохранен, но не отправлен (ошибка отправки)"
        else:
            status_text = f"{'✏️ Ответ изменен' if is_editing else '✅ Ответ отправлен'}"
        
        await message.answer(
            f"{status_text} на запрос #{request_id}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при обработке ответа на запрос: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке ответа")
        await state.clear()

@router.callback_query(F.data.startswith("archive_price_"), is_price_request_callback)
async def archive_price_request(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Архивирование запроса
    """
    try:
        request_id = int(callback.data.split("_")[2])
        
        # Получаем запрос
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
        
        # Проверяем, что запрос отвечен
        if request.status == "PENDING":
            await callback.answer(
                "❌ Нельзя архивировать запрос без ответа!",
                show_alert=True
            )
            return
        
        # Архивируем запрос
        request.status = "ARCHIVED"
        request.archived_at = datetime.now()
        await session.commit()
        
        await callback.answer("✅ Запрос перемещен в архив")
        
        # Возвращаемся к списку запросов
        await show_price_requests(callback, session)
        
    except Exception as e:
        logger.error(f"Ошибка при архивации запроса: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при архивации")

@router.callback_query(F.data.startswith("archived_page_"), is_price_request_callback)
@router.callback_query(F.data == "archived_price_requests", is_price_request_callback)
async def show_archived_requests(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает список архивных запросов с пагинацией
    """
    try:
        logger.info(f"Администратор {callback.from_user.id} открыл архив запросов")
        await callback.answer()
        
        # Определяем номер страницы
        page = 1
        if callback.data.startswith("archived_page_"):
            page = int(callback.data.split("_")[2])
        
        # Получаем все архивные запросы
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.status == "ARCHIVED")
            .order_by(PriceRequest.archived_at.desc())
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service),
                selectinload(PriceRequest.admin)
            )
        )
        all_requests = result.scalars().all()
        
        if not all_requests:
            await callback.message.edit_text(
                "📦 Архив запросов пуст",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="↩️ К активным запросам",
                        callback_data="filter_pending_requests"
                    )
                ]]),
                parse_mode="HTML"
            )
            return
        
        # Группируем запросы по датам
        grouped_requests = {}
        for req in all_requests:
            date = req.archived_at.strftime('%d.%m.%Y')
            if date not in grouped_requests:
                grouped_requests[date] = []
            grouped_requests[date].append(req)
        
        # Настройки пагинации
        ITEMS_PER_PAGE = 10
        dates = list(grouped_requests.keys())
        total_pages = (len(all_requests) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        # Получаем запросы для текущей страницы
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_requests = all_requests[start_idx:end_idx]
        
        text = f"📦 Архив запросов (страница {page}/{total_pages}):\n\n"
        keyboard = []
        
        # Группируем текущие запросы по датам
        current_grouped = {}
        for req in current_requests:
            date = req.archived_at.strftime('%d.%m.%Y')
            if date not in current_grouped:
                current_grouped[date] = []
            current_grouped[date].append(req)
        
        # Формируем текст для каждой даты
        for date, requests in current_grouped.items():
            text += f"📅 {date}:\n"
            for req in requests:
                status = "✅" if req.admin_response else "❌"
                text += (
                    f"#{req.id} {status} {req.user.full_name} • "
                    f"{req.service.name[:20]}{'...' if len(req.service.name) > 20 else ''}\n"
                )
            text += "\n"
            
            # Добавляем кнопки для запросов этой даты
            row = []
            for req in requests:
                if len(row) == 2:  # Максимум 2 кнопки в ряду
                    keyboard.append(row)
                    row = []
                row.append(
                    InlineKeyboardButton(
                        text=f"📋 #{req.id}",
                        callback_data=f"price_request_details_{req.id}"
                    )
                )
            if row:  # Добавляем оставшиеся кнопки
                keyboard.append(row)
        
        # Добавляем кнопки пагинации
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"archived_page_{page-1}"
                )
            )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"archived_page_{page+1}"
                )
            )
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ К активным запросам",
                callback_data="filter_pending_requests"
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке архива: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке архива",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                    callback_data="manage_price_requests"
                )
            ]]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("price_request_details_"), is_price_request_callback)
async def view_price_request_details(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Просмотр деталей запроса на расчет стоимости
    """
    try:
        request_id = int(callback.data.split("_")[3])
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service),
                selectinload(PriceRequest.admin)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
        
        # Формируем детальную информацию
        status_emoji = "🕐" if request.status == "PENDING" else "✅"
        text = (
            f"{status_emoji} Запрос #{request.id}\n\n"
            f"<b>👤 Клиент:</b> {request.user.full_name}\n"
            f"<b>📱 Телефон:</b> {request.user.phone_number or 'Не указан'}\n"
            f"<b>🔧 Услуга:</b> {request.service.name}\n"
            f"<b>🚘 Автомобиль:</b> {request.car_info}\n"
            f"<b>📅 Создан:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if request.admin_response:
            answered_at_str = request.answered_at.strftime('%d.%m.%Y %H:%M') if request.answered_at else "Дата не указана"
            text += (
                f"\n<b>💬 Ответ от {request.admin.full_name}:</b>\n"
                f"{request.admin_response}\n"
                f"<b>📅 Отвечено:</b> {answered_at_str}\n"
            )
        
        # Создаем клавиатуру действий
        keyboard = []
        
        if request.status == "PENDING":
            keyboard.append([
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"respond_price_{request.id}"
                )
            ])
        else:
            keyboard.extend([
                [
                    InlineKeyboardButton(
                        text="✏️ Изменить ответ",
                        callback_data=f"edit_price_response_{request.id}"
                    ),
                    InlineKeyboardButton(
                        text="📦 В архив",
                        callback_data=f"archive_price_{request.id}"
                    )
                ]
            ])
        
        # Добавляем кнопку возврата в зависимости от статуса запроса
        back_callback = "filter_pending_requests" if request.status == "PENDING" else "filter_answered_requests"
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data=back_callback
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре деталей запроса: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при загрузке информации")

@router.callback_query(F.data.startswith("edit_price_response_"), is_price_request_callback)
async def start_edit_price_response(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса редактирования ответа
    """
    try:
        request_id = int(callback.data.split("_")[3])
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
        
        # Сохраняем ID запроса и пометку, что это редактирование
        await state.update_data(request_id=request_id, is_editing=True)
        await state.set_state(PriceRequestStates.waiting_for_response)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"price_request_details_{request_id}"
            )]
        ])
        
        text = (
            f"<b>✏️ Редактирование ответа на запрос #{request_id}</b>\n\n"
            f"<b>👤 Клиент:</b> {request.user.full_name}\n"
            f"<b>🔧 Услуга:</b> {request.service.name}\n"
            f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
            f"<b>💬 Текущий ответ:</b>\n{request.admin_response}\n\n"
            "<b>📝 Введите новый ответ:</b>"
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при начале редактирования ответа: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(F.data == "filter_pending_requests", is_price_request_callback)
async def filter_pending_requests(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает только ожидающие ответа запросы
    """
    try:
        await callback.answer()
        
        result = await session.execute(
            select(PriceRequest)
            .where(
                PriceRequest.status == "PENDING"
            )
            .order_by(PriceRequest.created_at.desc())
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        requests = result.scalars().all()
        
        if not requests:
            await callback.message.edit_text(
                "🔍 Нет ожидающих ответа запросов",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="↩️ Назад",
                        callback_data="manage_price_requests"
                    )
                ]]),
                parse_mode="HTML"
            )
            return
        
        text = "<b>🕐 Ожидающие ответа запросы:</b>\n\n"
        keyboard = []
        
        for req in requests:
            text += (
                f"#{req.id} от {req.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"<b>👤 {req.user.full_name}</b>\n"
                f"<b>🔧 {req.service.name}</b>\n"
                f"<b>🚘 {req.car_info}</b>\n\n"
            )
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"💬 Ответить #{req.id}",
                    callback_data=f"respond_price_{req.id}"
                ),
                InlineKeyboardButton(
                    text="📋 Детали",
                    callback_data=f"price_request_details_{req.id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="manage_price_requests"
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при фильтрации запросов: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке запросов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                    callback_data="manage_price_requests"
                )
            ]]),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "filter_answered_requests", is_price_request_callback)
async def filter_answered_requests(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Показывает только отвеченные запросы
    """
    try:
        await callback.answer()
        
        result = await session.execute(
            select(PriceRequest)
            .where(
                PriceRequest.status == "ANSWERED"
            )
            .order_by(PriceRequest.answered_at.desc())
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service),
                selectinload(PriceRequest.admin)
            )
        )
        requests = result.scalars().all()
        
        if not requests:
            await callback.message.edit_text(
                "🔍 Нет отвеченных запросов",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="↩️ Назад",
                        callback_data="manage_price_requests"
                    )
                ]]),
                parse_mode="HTML"
            )
            return
        
        text = "<b>✅ Отвеченные запросы:</b>\n\n"
        keyboard = []
        
        for req in requests:
            text += (
                f"#{req.id} от {req.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"<b>👤 {req.user.full_name}</b>\n"
                f"<b>🔧 {req.service.name}</b>\n"
                f"<b>🚘 {req.car_info}</b>\n"
                f"<b>💬 Ответ от {req.admin.full_name}:</b>\n{req.admin_response}\n\n"
            )
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"✏️ Изменить #{req.id}",
                    callback_data=f"edit_price_response_{req.id}"
                ),
                InlineKeyboardButton(
                    text="📦 В архив",
                    callback_data=f"confirm_archive_{req.id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data="manage_price_requests"
            )
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при фильтрации запросов: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке запросов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                    callback_data="manage_price_requests"
                )
            ]]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("confirm_archive_"), is_price_request_callback)
async def confirm_archive_request(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Запрос подтверждения архивации
    """
    try:
        request_id = int(callback.data.split("_")[2])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, архивировать",
                    callback_data=f"archive_price_{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Нет, отмена",
                    callback_data=f"price_request_details_{request_id}"
                )
            ]
        ])
        
        await callback.message.edit_text(
            f"<b>❓ Вы уверены, что хотите архивировать запрос #{request_id}?</b>\n"
            "После архивации запрос будет доступен только в архиве.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при подтверждении архивации: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

@router.callback_query(F.data.startswith("send_prepared_response_"), is_price_request_callback)
async def send_prepared_response(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Отправка подготовленного ответа
    """
    try:
        request_id = int(callback.data.split("_")[3])
        data = await state.get_data()
        prepared_response = data.get("prepared_response")
        
        if not prepared_response:
            await callback.answer("❌ Ответ не найден")
            return
            
        # Получаем запрос
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            await state.clear()
            return
        
        # Получаем или создаем администратора
        admin_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        admin = admin_result.scalar_one_or_none()
        
        if not admin:
            admin = User(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
                is_admin=True
            )
            session.add(admin)
            await session.flush()
        
        # Обновляем запрос
        request.admin_response = prepared_response
        request.admin_id = admin.id
        request.status = "ANSWERED"
        request.answered_at = datetime.now()
        
        await session.commit()
        
        # Отправляем ответ клиенту
        try:
            text = (
                "<b>💰 Расчет стоимости по вашему запросу:</b>\n\n"
                f"<b>🔧 Услуга:</b> {request.service.name}\n"
                f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
                f"<b>💬 Ответ менеджера:</b>\n{request.admin_response}"
            )
            
            await bot.send_message(
                request.user.telegram_id,
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📝 Записаться",
                        callback_data=f"book_from_price_request_{request.service_id}_{request_id}"
                    )
                ]])
            )
        except Exception as e:
            logger.error(f"Не удалось отправить ответ клиенту: {e}")
            await callback.answer("❌ Не удалось отправить ответ клиенту", show_alert=True)
        
        # Очищаем состояние
        await state.clear()
        
        # Отправляем подтверждение администратору
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Архивировать",
                    callback_data=f"archive_price_{request_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"edit_price_response_{request_id}"
                )
            ],
            [InlineKeyboardButton(
                text="↩️ К списку запросов",
                callback_data="manage_price_requests"
            )]
        ])
        
        await callback.message.edit_text(
            f"<b>✅ Ответ отправлен на запрос #{request_id}</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке подготовленного ответа: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при отправке ответа", show_alert=True)
        await state.clear()
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при отправке ответа</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                    callback_data="manage_price_requests"
                )
            ]])
        )

@router.callback_query(F.data.startswith("edit_prepared_response_"), is_price_request_callback)
async def edit_prepared_response(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Редактирование подготовленного ответа
    """
    try:
        request_id = int(callback.data.split("_")[3])
        data = await state.get_data()
        prepared_response = data.get("prepared_response")
        
        if not prepared_response:
            await callback.answer("❌ Ответ не найден")
            return
        
        # Сохраняем текущий ответ и ID запроса
        await state.update_data(
            request_id=request_id,
            current_response=prepared_response
        )
        await state.set_state(PriceRequestStates.editing_response)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"respond_price_{request_id}"
            )
        ]])
        
        text = (
            f"<b>✏️ Редактирование ответа на запрос #{request_id}</b>\n\n"
            f"<b>Текущий ответ:</b>\n{prepared_response}\n\n"
            "<b>📝 Введите новый ответ:</b>"
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при начале редактирования ответа: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@router.message(PriceRequestStates.editing_response)
async def process_edited_response(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка отредактированного ответа
    """
    try:
        data = await state.get_data()
        request_id = data.get("request_id")
        
        # Получаем запрос
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await message.answer("❌ Запрос не найден")
            await state.clear()
            return
        
        # Обновляем ответ
        request.admin_response = message.text.strip()
        await session.commit()
        
        # Отправляем обновленный ответ клиенту
        try:
            text = (
                f"<b>💰 Обновлённый расчет стоимости по вашему запросу:</b>\n\n"
                f"<b>🔧 Услуга:</b> {request.service.name}\n"
                f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
                f"<b>💬 Ответ менеджера:</b>\n{request.admin_response}"
            )
            
            await bot.send_message(
                request.user.telegram_id,
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📝 Записаться",
                        callback_data=f"book_from_price_request_{request.service_id}_{request_id}"
                    )
                ]])
            )
        except Exception as e:
            logger.error(f"Не удалось отправить обновленный ответ клиенту: {e}")
        
        # Очищаем состояние
        await state.clear()
        
        # Отправляем подтверждение администратору
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Архивировать",
                    callback_data=f"archive_price_{request_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить ещё раз",
                    callback_data=f"edit_price_response_{request_id}"
                )
            ],
            [InlineKeyboardButton(
                text="↩️ К списку запросов",
                callback_data="manage_price_requests"
            )]
        ])
        
        await message.answer(
            f"<b>✅ Ответ на запрос цены #{request_id} обновлен</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке отредактированного ответа: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обновлении ответа",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ К списку запросов",
                    callback_data="manage_price_requests"
                )
            ]]),
            parse_mode="HTML"
        )
        await state.clear()

@router.callback_query(F.data.startswith("custom_response_"), is_price_request_callback)
async def start_custom_response(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Начало процесса написания своего ответа
    """
    try:
        request_id = int(callback.data.split("_")[2])
        
        result = await session.execute(
            select(PriceRequest)
            .where(PriceRequest.id == request_id)
            .options(
                selectinload(PriceRequest.user),
                selectinload(PriceRequest.service)
            )
        )
        request = result.scalar_one_or_none()
        
        if not request:
            await callback.answer("❌ Запрос не найден")
            return
        
        # Сохраняем ID запроса в состояние
        await state.update_data(request_id=request_id)
        await state.set_state(PriceRequestStates.waiting_for_response)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"respond_price_{request_id}"
            )
        ]])
        
        text = (
            f"<b>💬 Напишите ответ на запрос цены #{request_id}</b>\n\n"
            f"<b>👤 Клиент:</b> {request.user.full_name}\n"
            f"<b>🔧 Услуга:</b> {request.service.name}\n"
            f"<b>🚘 Автомобиль:</b> {request.car_info}\n\n"
            "<b>📝 Введите ваш ответ:</b>"
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при начале написания ответа: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)
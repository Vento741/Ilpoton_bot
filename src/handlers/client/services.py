# src/handlers/client/services.py

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from config.settings import settings
from database.models import Service, User, PriceRequest
from keyboards.client.client import get_main_keyboard, get_services_keyboard
from states.client import ServiceStates
from core.utils.logger import log_error

router = Router()

@router.message(F.text == "💰 Услуги и цены")
async def show_services_command(message: Message, session: AsyncSession) -> None:
    """
    Показывает список услуг и цен (обработчик текстовой команды)
    """
    try:
        logger.info(f"Пользователь {message.from_user.id} открыл список услуг")
        
        # Получаем все услуги из БД
        services = await session.execute(
            select(Service)
            .order_by(Service.id)
        )
        services = services.scalars().all()
        
        if not services:
            await message.answer(
                "❌ К сожалению, список услуг пока пуст.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Формируем текст со списком услуг в HTML
        message_text = (
            "<b>🚘 Услуги и цены</b>\n\n"
            "<b>⚠️ Обратите внимание:</b> указанные цены являются ориентировочными.\n"
            "<b>Для получения точной стоимости, пожалуйста:</b>\n"
            "1️⃣ <code>Выберите интересующую услугу</code>\n"
            "2️⃣ <code>В сообщении укажите марку и модель вашего автомобиля</code>\n" 
            "3️⃣ <code>Получите точный расчет (в течение 15 минут)</code>\n\n"
            "<b>Доступные услуги:</b>\n\n"
        )
        
        # Создаем клавиатуру с услугами
        keyboard = get_services_keyboard(services)
        
        # Добавляем кнопку возврата в главное меню
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text="🔙 Назад в главное меню",
                callback_data="back_to_main"
            )
        ])
        
        await message.answer(
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "❌ Произошла ошибка при загрузке списка услуг",
            reply_markup=get_main_keyboard()
        )

@router.callback_query(F.data == "services_and_prices")
async def show_services(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """
    Показывает список услуг и цен
    """
    try:
        logger.info(f"Пользователь {callback.from_user.id} открыл список услуг")
        await callback.answer()
        
        # Получаем все услуги из БД
        services = await session.execute(
            select(Service)
            .order_by(Service.id)
        )
        services = services.scalars().all()
        
        if not services:
            await callback.message.answer(
                "❌ К сожалению, список услуг пока пуст.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
                ])
            )
            return
        
        # Формируем текст со списком услуг в HTML
        message_text = (
            "<b>🚘 Услуги и цены</b>\n\n"
            "<b>⚠️ Обратите внимание:</b> указанные цены являются ориентировочными.\n"
            "<b>Для получения точной стоимости, пожалуйста:</b>\n"
            "1️⃣ <code>Выберите интересующую услугу</code>\n"
            "2️⃣ <code>В сообщении укажите марку и модель вашего автомобиля</code>\n" 
            "3️⃣ <code>Получите точный расчет (в течение 15 минут)</code>\n\n"
            "<b>Доступные услуги:</b>\n\n"
        )
        
        # Создаем клавиатуру с услугами
        keyboard = get_services_keyboard(services)
        
        # Добавляем кнопку возврата в главное меню
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text="🔙 Назад в главное меню",
                callback_data="back_to_main"
            )
        ])
        
        try:
            # Пытаемся получить ID предыдущего сообщения из состояния
            data = await state.get_data()
            previous_message_id = data.get("previous_message_id")
            
            if previous_message_id:
                try:
                    # Пытаемся удалить предыдущее сообщение
                    await callback.message.bot.delete_message(
                        callback.message.chat.id,
                        previous_message_id
                    )
                except Exception as e:
                    logger.error(f"Не удалось удалить предыдущее сообщение: {e}")
            
            # Пробуем отредактировать текущее сообщение
            edited_message = await callback.message.edit_text(
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            # Сохраняем ID нового сообщения
            await state.update_data(previous_message_id=edited_message.message_id)
            
        except Exception as e:
            # Если не получилось отредактировать (сообщение было удалено),
            # отправляем новое сообщение
            new_message = await callback.message.answer(
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            # Сохраняем ID нового сообщения
            await state.update_data(previous_message_id=new_message.message_id)
        
    except Exception as e:
        log_error(e)
        try:
            await callback.message.edit_text(
                "❌ Произошла ошибка при загрузке списка услуг",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
                ])
            )
        except:
            await callback.message.answer(
                "❌ Произошла ошибка при загрузке списка услуг",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
                ])
            )

@router.callback_query(F.data.startswith("appointment_select_service_"))
async def select_service(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка выбора услуги
    """
    try:
        service_id = int(callback.data.split("_")[3])
        
        # Получаем выбранную услугу
        service = await session.get(Service, service_id)
        if not service:
            await callback.answer("❌ Услуга не найдена")
            return
        
        # Сохраняем ID услуги в состояние
        await state.update_data(service_id=service_id)
        
        # Создаем клавиатуру с кнопками
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💰 Запросить стоимость",
                callback_data=f"request_price_{service_id}"
            )],
            [InlineKeyboardButton(
                text="↩️ Назад к списку услуг",
                callback_data="services_and_prices"
            )]
        ])
        
        message_text = (
            f"<b>🔽 Вы выбрали услугу:</b>\n\n"
            f"<b>{service.name}</b>\n"
            f"<i>{service.description}</i>\n\n"
            f"<b>💰 Стоимость:</b> <code>от {service.price}₽</code>\n"
            f"<b>🕒 Длительность:</b> <code>от {service.duration} мин.</code>\n\n"
            f"<i>Нажмите кнопку «Запросить стоимость», чтобы получить точный расчет для вашего автомобиля.</i>"
        )

        # Проверяем наличие изображения
        if service.image_id:
            sent_message = await callback.message.answer_photo(
                photo=service.image_id,
                caption=message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.update_data(previous_message_id=sent_message.message_id)
            await callback.message.delete()
        else:
            edited_message = await callback.message.edit_text(
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await state.update_data(previous_message_id=edited_message.message_id)
        
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при выборе услуги</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Назад", callback_data="services_and_prices")]
            ]),
            parse_mode="HTML"
        )

# Добавляем новый обработчик для кнопки "Запросить стоимость"
@router.callback_query(F.data.startswith("request_price_"))
async def request_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Обработка нажатия кнопки запроса стоимости
    """
    try:
        service_id = int(callback.data.split("_")[2])
        
        # Получаем выбранную услугу
        service = await session.get(Service, service_id)
        if not service:
            await callback.answer("❌ Услуга не найдена")
            return
        
        # Устанавливаем состояние ожидания информации об автомобиле
        await state.set_state(ServiceStates.waiting_for_car_info)
        
        # Создаем клавиатуру с кнопкой отмены
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="↩️ Отменить запрос",
                callback_data=f"appointment_select_service_{service_id}"
            )]
        ])
        
        message_text = (
            f"<b>📝 Расчет стоимости услуги</b>\n"
            f"<i>{service.name}</i>\n\n"
            f"<b>Пожалуйста, укажите:</b>\n"
            f"<code>• Марку автомобиля</code>\n"
            f"<code>• Модель</code>\n"
            f"<code>• Год выпуска</code>\n\n"
            f"<b>✳️ Примеры:</b>\n"
            f"<i>🆗Toyota Camry 2020</i>\n"
            f"<i>🆗Тойота Камри 2020</i>"
        )

        # Получаем данные о предыдущем сообщении
        data = await state.get_data()
        previous_message_id = data.get("previous_message_id")

        # Отправляем новое сообщение
        if callback.message.photo:
            new_message = await callback.message.answer_photo(
                photo=callback.message.photo[-1].file_id,
                caption=message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            new_message = await callback.message.answer(
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        # Сохраняем ID нового сообщения
        await state.update_data(previous_message_id=new_message.message_id)

        # Удаляем старые сообщения
        try:
            # Удаляем сообщение с кнопкой запроса
            await callback.message.delete()
        except Exception as e:
            # Игнорируем ошибку, если сообщение уже удалено
            if "message to delete not found" not in str(e).lower():
                logger.error(f"Не удалось удалить сообщение callback: {e}")

        if previous_message_id:
            try:
                # Удаляем предыдущее сохраненное сообщение
                await callback.message.bot.delete_message(
                    chat_id=callback.message.chat.id,
                    message_id=previous_message_id
                )
            except Exception as e:
                # Игнорируем ошибку, если сообщение уже удалено
                if "message to delete not found" not in str(e).lower():
                    logger.error(f"Не удалось удалить предыдущее сообщение: {e}")
        
    except Exception as e:
        log_error(e)
        await callback.message.answer(
            "<b>❌ Произошла ошибка при запросе стоимости</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Назад", callback_data=f"appointment_select_service_{service_id}")]
            ]),
            parse_mode="HTML"
        )

@router.message(ServiceStates.waiting_for_car_info, F.text)
async def process_car_info(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка информации об автомобиле
    """
    try:
        # Проверяем, не является ли пользователь ботом
        if message.from_user.username and message.from_user.username.lower().endswith('bot'):
            logger.warning(f"Попытка создания запроса от бота: {message.from_user.username}. Запрос будет обработан, но требуется проверка логики.")
        
        # Получаем данные из состояния
        data = await state.get_data()
        service_id = data.get("service_id")
        previous_message_id = data.get("previous_message_id")
        
        if not service_id:
            await message.answer(
                "<b>❌ Произошла ошибка. Пожалуйста, начните процесс заново.</b>",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return
            
        # Получаем услугу
        service = await session.get(Service, service_id)
        if not service:
            await message.answer(
                "<b>❌ Услуга не найдена. Пожалуйста, начните процесс заново.</b>",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Сохраняем информацию об автомобиле в состояние
        await state.update_data(car_info=message.text)
        
        # Спрашиваем о дополнительных вопросах
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Да, есть вопрос",
                    callback_data="add_question"
                ),
                InlineKeyboardButton(
                    text="➡️ Нет, отправить",
                    callback_data="send_request"
                )
            ]
        ])
        
        sent_message = await message.answer(
            "<b>🚗 Информация об автомобиле получена</b>\n\n"
            "<i>Есть ли у вас дополнительные вопросы по услуге?</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Сохраняем ID сообщения для последующего удаления
        await state.update_data(question_message_id=sent_message.message_id)
        
        # Обновляем состояние
        await state.set_state(ServiceStates.waiting_for_question_choice)
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "<b>❌ Произошла ошибка при обработке запроса</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()

@router.callback_query(F.data == "add_question", ServiceStates.waiting_for_question_choice)
async def request_additional_question(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрашивает дополнительный вопрос у пользователя
    """
    try:
        # Удаляем предыдущее сообщение с кнопками
        await callback.message.delete()
        
        await callback.message.answer(
            "<b>📝 Пожалуйста, напишите ваш вопрос:</b>\n\n"
            "<i>Опишите, что вас интересует, и мы обязательно учтем это при расчете стоимости.</i>",
            parse_mode="HTML"
        )
        
        # Обновляем состояние
        await state.set_state(ServiceStates.waiting_for_question)
        
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка. Пожалуйста, попробуйте позже.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()

@router.message(ServiceStates.waiting_for_question, F.text)
async def process_additional_question(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Обработка дополнительного вопроса
    """
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        car_info = data.get("car_info")
        
        # Создаем заявку с дополнительным вопросом
        await create_price_request(message, state, session, bot, car_info, message.text)
        
    except Exception as e:
        log_error(e)
        await message.answer(
            "<b>❌ Произошла ошибка при отправке заявки</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "send_request", ServiceStates.waiting_for_question_choice)
async def send_request_without_question(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """
    Отправка заявки без дополнительного вопроса
    """
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # Удаляем сообщение с кнопками
        await callback.message.delete()
        
        # Создаем заявку, передавая callback вместо callback.message
        # Это позволит использовать правильный from_user (пользователя, а не бота)
        await create_price_request(callback, state, session, bot, data["car_info"])
        
    except Exception as e:
        log_error(e)
        await callback.message.edit_text(
            "<b>❌ Произошла ошибка при отправке заявки</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )

async def create_price_request(event, state: FSMContext, session: AsyncSession, bot: Bot, car_info: str, additional_question: str = None) -> None:
    """
    Создание заявки на расчет стоимости
    
    Args:
        event: Может быть Message или CallbackQuery
        state: FSM контекст
        session: Сессия базы данных
        bot: Экземпляр бота
        car_info: Информация об автомобиле
        additional_question: Дополнительный вопрос (опционально)
    """
    try:
        data = await state.get_data()
        service_id = data.get("service_id")
        
        # Определяем, является ли event сообщением или callback
        if hasattr(event, 'message'):
            # Это CallbackQuery
            user_id = event.from_user.id
            username = event.from_user.username
            full_name = event.from_user.full_name
            chat_id = event.message.chat.id
        else:
            # Это Message
            user_id = event.from_user.id
            username = event.from_user.username
            full_name = event.from_user.full_name
            chat_id = event.chat.id
        
        # Логируем информацию о пользователе для отладки
        logger.info(f"Создание запроса на расчет стоимости от пользователя: ID={user_id}, username={username}, full_name={full_name}")
        
        # Проверяем, не является ли пользователь ботом
        is_bot = False
        if username and username.lower().endswith('bot'):
            is_bot = True
            logger.warning(f"Попытка создания запроса от бота: {username}. Необходимо проверить логику работы.")
        
        # Получаем или создаем пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=user_id,
                username=username,
                full_name=full_name
            )
            session.add(user)
            await session.flush()
        
        # Получаем услугу
        service = await session.get(Service, service_id)
        
        # Создаем запрос на расчет стоимости
        price_request = PriceRequest(
            user_id=user.id,
            service_id=service_id,
            car_info=car_info,
            additional_question=additional_question,
            status="PENDING"
        )
        session.add(price_request)
        await session.commit()
        
        # Отправляем подтверждение пользователю
        confirmation_text = (
            "<b>✅ Спасибо! Ваша заявка принята.</b>\n\n"
            f"<b>📌 Услуга:</b> <i>{service.name}</i>\n"
            f"<b>🚘 Автомобиль:</b> <code>{car_info}</code>"
        )
        
        if additional_question:
            confirmation_text += f"\n<b>❓ Ваш вопрос:</b> <i>{additional_question}</i>"
            
        confirmation_text += (
            "\n\n<b>👨‍💼 Наш менеджер свяжется с вами в ближайшее время\n"
            "для уточнения деталей и расчета точной стоимости.</b>"
        )
        
        # Отправляем сообщение в зависимости от типа события
        if hasattr(event, 'message'):
            # Это CallbackQuery
            await bot.send_message(
                chat_id,
                confirmation_text,
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
        else:
            # Это Message
            await event.answer(
                confirmation_text,
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
        
        # Уведомляем администраторов
        admin_message = (
            "<b>🆕 НОВЫЙ ЗАПРОС РАСЧЕТА СТОИМОСТИ</b>\n\n"
            f"<b>👤 Клиент:</b> <code>{user.full_name}</code>\n"
            f"<b>📱 Телефон:</b> <code>{user.phone_number or 'Не указан'}</code>\n"
            f"<b>🚘 Автомобиль:</b> <code>{car_info}</code>\n"
            f"<b>💇‍♂️ Услуга:</b> <i>{service.name}</i>\n"
            f"<b>💰 Базовая стоимость:</b> <code>от {service.price}₽</code>"
        )
        
        if is_bot:
            admin_message += f"\n\n⚠️ <b>Внимание!</b> Запрос создан от имени бота ({username}). Возможно, требуется проверка логики работы."
        
        if additional_question:
            admin_message += f"\n<b>❓ Вопрос клиента:</b> <i>{additional_question}</i>"
        
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Ответить",
                callback_data=f"respond_price_{price_request.id}"
            )]
        ])
        
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    admin_message,
                    reply_markup=admin_keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        log_error(e)
        raise e


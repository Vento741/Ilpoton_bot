# src/handlers/client/base.py

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select
from aiogram.fsm.context import FSMContext
from aiogram.enums.parse_mode import ParseMode
import re
from loguru import logger

from core.utils import START_MESSAGE
from database.models import User
from keyboards.client.client import get_main_keyboard
from config.settings import settings
from core.utils.referral import generate_referral_link, get_referral_stats

# Создаем роутер
router = Router()

# Паттерн для извлечения ID реферера из deep link
REFERRAL_PATTERN = r"ref_(\d+)"

@router.message(CommandStart(), ~F.from_user.id.in_(settings.admin_ids))
async def cmd_start(message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot, command: CommandStart) -> None:
    """
    Единый обработчик команды /start для обычных пользователей
    Обрабатывает как обычный старт, так и приглашения по реферальной ссылке
    """
    user_id = message.from_user.id
    
    # Получаем параметр из текста сообщения
    # Например, из "/start ref_123456" извлекаем "ref_123456"
    command_text = message.text
    deep_link = None
    if ' ' in command_text:
        deep_link = command_text.split(' ', 1)[1]
    
    logger.info(f"Обработка команды /start от пользователя {user_id}, параметр: {deep_link}")
    
    # Если есть deep_link, обрабатываем реферальную ссылку
    referral_processed = False
    referrer_id = None
    
    if deep_link:
        logger.info(f"Получена команда /start с deep_link: {deep_link} от пользователя {user_id}")
        
        # Ищем ID реферера в deep_link
        match = re.search(REFERRAL_PATTERN, deep_link)
        
        if match:
            referrer_id = int(match.group(1))
            logger.info(f"Извлечен ID реферера: {referrer_id} из deep_link для пользователя {user_id}")
            
            # Проверяем, что пользователь не указывает сам себя как реферера
            if referrer_id == user_id:
                logger.warning(f"Пользователь {user_id} пытается указать себя как реферера")
            else:
                # Обрабатываем реферальную связь
                referral_processed = await process_referral_relation(user_id, referrer_id, session, bot)
        else:
            logger.warning(f"Не удалось извлечь ID реферера из deep_link: {deep_link}")
    
    # Если у пользователя нет номера телефона, запрашиваем его
    if not user.phone_number:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Отправить контакт", request_contact=True)],
                [KeyboardButton(text="❌ Отмена")]
            ],
            resize_keyboard=True
        )
        
        # Сохраняем сообщение для последующего удаления
        message = await message.answer(
            "Для начала работы, пожалуйста, поделитесь своим номером телефона:",
            reply_markup=keyboard
        )
        
        # Сохраняем ID сообщения и информацию о реферальной ссылке
        await state.update_data(message_to_delete=message.message_id, referral_processed=referral_processed, referrer_id=referrer_id)
        return

    # Если процесс обработки реферальной ссылки завершен успешно, показываем специальное сообщение
    if referral_processed:
        # Получаем реферальную ссылку и статистику для показа пользователю
        ref_link = await generate_referral_link(user_id, bot)
        invited_count, attempts = await get_referral_stats(user_id, session)
        
        await message.answer(
            f"🎉 <b>Добро пожаловать в ILPO-TON!</b>\n\n"
            f"Вы пришли по реферальной ссылке. Пригласивший вас пользователь получил бонусную попытку "
            f"в слот-машине! Вы тоже можете приглашать друзей и получать бонусы.\n\n"
            f"🔗 Ваша реферальная ссылка: {ref_link}\n"
            f"👥 Приглашено друзей: {invited_count}\n"
            f"🎰 Доступных попыток: {attempts}",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        # Отправляем стандартное приветственное сообщение
        await message.answer(START_MESSAGE, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)


async def process_referral_relation(user_id: int, referrer_id: int, session: AsyncSession, bot: Bot) -> bool:
    """
    Обработка реферальной связи между пользователями
    
    Args:
        user_id: ID пользователя, который перешел по ссылке
        referrer_id: ID пользователя, пригласившего по ссылке
        session: Сессия базы данных
        bot: Экземпляр бота для отправки уведомлений
        
    Returns:
        bool: Успешно ли обработана реферальная связь
    """
    try:
        # Находим пользователя в БД
        user_result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        # Находим реферера в БД
        referrer_result = await session.execute(
            select(User).where(User.telegram_id == referrer_id)
        )
        referrer = referrer_result.scalar_one_or_none()
        
        # Проверяем, существуют ли оба пользователя
        if not user:
            logger.warning(f"Пользователь {user_id} не найден в базе при обработке реферальной связи")
            return False
            
        if not referrer:
            logger.warning(f"Реферер {referrer_id} не найден в базе")
            return False
            
        # Проверяем, не установлен ли уже реферер у пользователя
        if user.referrer_id:
            logger.info(f"Пользователь {user_id} уже имеет реферера {user.referrer_id}")
            return False
            
        # Получаем ID реферера в БД для установки связи
        referrer_db_id = referrer.id
        
        # Устанавливаем связь и увеличиваем счетчики напрямую через SQL-запросы
        # 1. Устанавливаем реферера для пользователя
        await session.execute(
            update(User)
            .where(User.telegram_id == user_id)
            .values(referrer_id=referrer_db_id)
        )
        
        # 2. Увеличиваем счетчик приглашенных и попыток для реферера
        await session.execute(
            update(User)
            .where(User.id == referrer_db_id)
            .values(
                invited_count=User.invited_count + 1,
                attempts=User.attempts + 2
            )
        )
        
        # Сохраняем изменения
        await session.commit()
        
        # Получаем обновленные данные реферера
        updated_referrer = await session.execute(
            select(User).where(User.id == referrer_db_id)
        )
        updated_referrer_data = updated_referrer.scalar_one_or_none()
        
        if updated_referrer_data:
            logger.info(f"Реферальная связь установлена: {user_id} <- {referrer_id}")
            logger.info(f"Пользователю {referrer_id} начислена попытка, текущее кол-во: {updated_referrer_data.attempts}")
            
            # Отправляем уведомление пригласившему
            notification_text = (
                f"🎉 <b>Поздравляем!</b> Пользователь перешел по вашей реферальной ссылке!\n\n"
                f"👤 Имя: {user.full_name}\n"
                f"🆔 ID: {user_id}\n\n"
                f"<i>Вам начислена дополнительная попытка в слот-машине.</i>\n"
                f"Текущее количество попыток: <b>{updated_referrer_data.attempts}</b>"
            )
            
            try:
                await bot.send_message(
                    chat_id=referrer_id,
                    text=notification_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Отправлено уведомление пользователю {referrer_id} о приглашенном {user_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о реферале: {e}")
                
            return True
        else:
            logger.error("Не удалось получить обновленные данные реферера")
            return False
    
    except Exception as e:
        logger.error(f"Ошибка при обработке реферальной связи: {e}")
        await session.rollback()
        return False


@router.message(F.contact)
async def handle_contact(message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot) -> None:
    """
    Обработчик получения контакта
    """
    logger.info("Получен контакт для обновления")
    
    # Получаем номер из контакта
    contact = message.contact
    phone_number = contact.phone_number
    
    # Проверяем, есть ли номер
    if not phone_number:
        await message.answer("❌ Не удалось получить номер телефона. Пожалуйста, попробуйте еще раз.")
        return
    
    # Проверяем, что контакт принадлежит пользователю
    if contact.user_id != message.from_user.id:
        await message.answer("❌ Пожалуйста, отправьте свой собственный контакт, используя кнопку ниже.")
        return
    
    # Форматируем номер телефона (убираем лишние символы)
    if not phone_number.startswith('+'):
        phone_number = '+' + phone_number
    
    # Обновляем номер телефона
    try:
        user.phone_number = phone_number
        await session.commit()
        logger.info(f"Номер обновлен на {phone_number}")
        
        # Отправляем сообщение об успешном сохранении
        await message.answer("✅ Номер телефона сохранен!", reply_markup=get_main_keyboard())
        
        # Получаем сохраненные данные о реферальной ссылке
        data = await state.get_data()
        message_to_delete = data.get("message_to_delete")
        referral_processed = data.get("referral_processed", False)
        referrer_id = data.get("referrer_id")
        
        # Удаляем сообщение с запросом контакта
        if message_to_delete:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=message_to_delete)
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения: {e}")
        
        # Если была обработана реферальная ссылка, показываем специальное сообщение
        if referral_processed:
            # Получаем данные для пользователя
            user_id = message.from_user.id
            ref_link = await generate_referral_link(user_id, bot)
            invited_count, attempts = await get_referral_stats(user_id, session)
            
            await message.answer(
                f"🎉 <b>Добро пожаловать в ILPO-TON!</b>\n\n"
                f"Вы пришли по реферальной ссылке. Пригласивший вас пользователь получил бонусную попытку "
                f"в слот-машине! Вы тоже можете приглашать друзей и получать бонусы.\n\n"
                f"🔗 Ваша реферальная ссылка: {ref_link}\n"
                f"👥 Приглашено друзей: {invited_count}\n"
                f"🎰 Доступных попыток: {attempts}",
                parse_mode=ParseMode.HTML
            )
        else:
            # Отправляем приветственное сообщение стандартное
            await message.answer(START_MESSAGE, parse_mode=ParseMode.HTML)
            
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении номера: {e}")
        await message.answer("❌ Произошла ошибка при сохранении номера. Пожалуйста, попробуйте позже.")


@router.message(F.text == "❌ Отмена")
async def cancel_contact_request(message: Message, state: FSMContext) -> None:
    """
    Отмена запроса контакта
    """
    await state.clear()
    await message.answer(
        "Для полноценной работы с ботом необходимо предоставить номер телефона.\n"
        "Вы можете сделать это позже через меню.",
        reply_markup=get_main_keyboard()
    )


@router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery) -> None:
    """
    Общий обработчик для возврата в главное меню из любого раздела бота
    """
    try:
        # Удаляем текущее сообщение с инлайн клавиатурой
        await callback.message.delete()
        
        # Отправляем новое сообщение с основной клавиатурой
        await callback.message.answer(
            "Вы вернулись в главное меню",
            reply_markup=get_main_keyboard()
        )
        
        # Отвечаем на callback
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при возврате в главное меню: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при возврате в главное меню",
            reply_markup=get_main_keyboard()
        ) 
"""
Обработчики для слот-машины
"""

from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.enums.parse_mode import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from loguru import logger
import re

from database.models import User, Prize, SlotSpin
from core.utils.slot_machine import generate_slot_combination, check_win, format_slot_result
from core.utils.referral import generate_referral_link, get_referral_stats
from core.utils.subscription import is_subscribed, get_channel_info, CHANNEL_ID
from keyboards.client.slot_machine import (
    get_slot_machine_keyboard, 
    get_subscription_keyboard, 
    get_prizes_list_keyboard, 
    get_prize_keyboard,
    get_win_celebration_keyboard
)
from core.utils.slot_machine import animate_slot_machine
from config.settings import settings

# Создаем роутер
router = Router()

# Обработчик команды /ref (показ реферальной ссылки)
@router.message(Command("ref"))
async def cmd_referral(
    message: Message, 
    session: AsyncSession,
    bot: Bot
):
    """
    Показывает реферальную ссылку и статистику
    """
    user_id = message.from_user.id
    
    # Получаем реферальную ссылку
    ref_link = await generate_referral_link(user_id, bot)
    
    # Получаем статистику рефералов
    invited_count, attempts = await get_referral_stats(user_id, session)
    
    await message.answer(
        f"📊 <b>Ваша реферальная статистика:</b>\n\n"
        f"👥 Приглашено друзей: <b>{invited_count}</b>\n"
        f"🎰 Доступных попыток в слот-машине: <b>{attempts}</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n{ref_link}\n\n"
        f"За каждого приглашенного друга вы получаете +1 попытку в слот-машине!",
        parse_mode=ParseMode.HTML
    )

# Обработчик текстовой команды для запуска слот-машины
@router.message(F.text == "🎰 Слот-машина")
async def slot_machine_menu(
    message: Message, 
    session: AsyncSession,
    bot: Bot
):
    """
    Показывает меню слот-машины
    """
    user_id = message.from_user.id
    
    # Проверяем подписку на канал
    if not await is_subscribed(user_id, bot):
        channel_name = await get_channel_info(bot) or "наш канал"
        await message.answer(
            f"❌ <b>Вы не подписаны на канал</b> {CHANNEL_ID}\n\n"
            f"Для доступа к слот-машине необходимо подписаться на канал.",
            reply_markup=get_subscription_keyboard(channel_name),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем пользователя из БД
    result = await session.execute(
        select(User).where(User.telegram_id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        return
    
    # Показываем информацию о слот-машине
    await message.answer(
        "🎰 <b>Слот-машина ILPO-TON</b>\n\n"
        "<i>Испытайте удачу и выиграйте ценные призы!</i>\n\n"
        f"<b>Доступно попыток:</b> {user.attempts if user else 1}\n\n"
        "<b>Правила:</b>\n"
        "• 3 одинаковых символа = <b>приз</b>\n"
        "• 2 или более 🍒 = <b>дополнительная попытка</b>\n"
        "• Базовая попытка: <b>1 раз в день</b>\n"
        "• Дополнительные попытки за <b>приглашенных друзей</b>",
        reply_markup=get_slot_machine_keyboard(),
        parse_mode=ParseMode.HTML
    )

# Обработчик проверки подписки
@router.callback_query(F.data == "check_subscription")
async def check_subscription(
    callback: CallbackQuery, 
    session: AsyncSession,
    bot: Bot
):
    """
    Проверяет, подписан ли пользователь на канал
    """
    await callback.answer()
    
    # Проверяем подписку на канал
    if await is_subscribed(callback.from_user.id, bot):
        await callback.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Теперь вы можете использовать слот-машину.",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        
        # Получаем пользователя из БД
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        # Показываем меню слот-машины
        await callback.message.answer(
            "🎰 <b>Слот-машина ILPO-TON</b>\n\n"
            "<i>Испытайте удачу и выиграйте ценные призы!</i>\n\n"
            f"<b>Доступно попыток:</b> {user.attempts if user else 1}\n\n"
            "<b>Правила:</b>\n"
            "• 3 одинаковых символа = <b>приз</b>\n"
            "• 2 или более 🍒 = <b>дополнительная попытка</b>\n"
            "• Базовая попытка: <b>1 раз в день</b>\n"
            "• Дополнительные попытки за <b>приглашенных друзей</b>",
            reply_markup=get_slot_machine_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        channel_name = await get_channel_info(bot) or "наш канал"
        await callback.message.edit_text(
            "❌ <b>Подписка не обнаружена</b>\n\n"
            f"Пожалуйста, подпишитесь на канал {CHANNEL_ID} и нажмите кнопку проверки снова.",
            reply_markup=get_subscription_keyboard(channel_name),
            parse_mode=ParseMode.HTML
        )

# Обработчик запуска слот-машины
@router.callback_query(F.data == "spin_slot")
async def spin_slot_machine(
    callback: CallbackQuery, 
    session: AsyncSession,
    bot: Bot
):
    """
    Обработчик кнопки запуска слот-машины
    """
    try:
        # Проверяем подписку на канал
        if not await is_subscribed(callback.from_user.id, bot):
            channel_name = await get_channel_info(bot)
            await callback.message.edit_text(
                "⚠️ Для игры в слот-машину необходимо быть подписанным на наш канал!",
                reply_markup=get_subscription_keyboard(channel_name or "наш канал")
            )
            return

        # Получаем пользователя из БД
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)
            return
            
        # Проверяем количество попыток
        if user.attempts <= 0:
            await callback.answer("❌ У вас закончились попытки!", show_alert=True)
            return
            
        # Уменьшаем количество попыток
        user.attempts -= 1
        await session.commit()
        
        # Генерируем комбинацию
        combination = generate_slot_combination()
        
        # Отправляем начальное сообщение
        initial_message = await callback.message.edit_text(
            "🎰 Крутим барабаны...\n\n" + format_slot_result(('❓', '❓', '❓'))
        )
        
        # Запускаем анимацию
        await animate_slot_machine(initial_message, combination)
        
        # Проверяем выигрыш
        prize_text, extra_attempts = check_win(combination)
        
        # Создаем запись о попытке в таблице slot_spins
        slot_spin = SlotSpin(
            user_id=user.id,
            combination=format_slot_result(combination),
            result=prize_text,
            created_at=datetime.now()
        )
        session.add(slot_spin)
        
        # Если выиграли приз (не просто доп. попытку)
        if prize_text != "Повезет в следующий раз!" and prize_text != "Дополнительная попытка":
            # Создаем запись о призе в БД
            new_prize = Prize(
                user_id=user.id,
                prize_name=prize_text,
                combination=format_slot_result(combination),
                status="PENDING",
                created_at=datetime.now()
            )
            session.add(new_prize)
            await session.flush()  # Чтобы получить ID приза
            
            # Связываем запись о попытке с призом
            slot_spin.prize_id = new_prize.id
            
            # Добавляем экстра попытки, если выиграли их
            if extra_attempts > 0:
                user.attempts += extra_attempts
            
            await session.commit()
            
            # Формируем текст с результатом
            result_text = (
                f"🎰 <b>Результат:</b>\n\n"
                f"{format_slot_result(combination)}\n\n"
                f"🎉 <b>Поздравляем! Вы выиграли:</b>\n"
                f"{prize_text}\n\n"
                f"Оставшиеся попытки: {user.attempts}"
            )
            
            # Отправляем сообщение с результатом и кнопкой информации о призе
            await callback.message.edit_text(
                result_text,
                reply_markup=get_win_celebration_keyboard(new_prize.id),
                parse_mode=ParseMode.HTML
            )
            
            # Уведомляем администраторов о выигрыше
            admin_notification = (
                f"🎯 <b>Новый выигрыш в слот-машине!</b>\n\n"
                f"👤 Игрок: {user.full_name}\n"
                f"🆔 ID: {user.telegram_id}\n"
                f"🎁 Приз: {prize_text}\n"
                f"🎰 Комбинация: {format_slot_result(combination)}"
            )
            
            # Создаем клавиатуру для администратора
            admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить приз",
                        callback_data=f"confirm_slot_prize_{new_prize.id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💬 Написать победителю",
                        url=f"tg://user?id={user.telegram_id}"
                    )
                ]
            ])
            
            for admin_id in settings.admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_notification,
                        reply_markup=admin_keyboard,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
                    
        else:
            # Если выиграли дополнительную попытку
            if prize_text == "Дополнительная попытка":
                user.attempts += extra_attempts
            
            # Сохраняем изменения
            await session.commit()
            
            # Формируем текст с результатом
            result_text = (
                f"🎰 <b>Результат:</b>\n\n"
                f"{format_slot_result(combination)}\n\n"
                f"{prize_text}\n\n"
                f"Оставшиеся попытки: {user.attempts}"
            )
            
            # Отправляем сообщение с результатом
            await callback.message.edit_text(
                result_text,
                reply_markup=get_slot_machine_keyboard(),
                parse_mode=ParseMode.HTML
            )
            
    except Exception as e:
        logger.error(f"Ошибка при вращении слот-машины: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка при вращении слот-машины", show_alert=True)

# Обработчик просмотра списка призов
@router.callback_query(F.data == "my_prizes")
@router.callback_query(F.data.startswith("prizes_page_"))
async def show_my_prizes(
    callback: CallbackQuery, 
    session: AsyncSession
):
    """
    Показывает список призов пользователя с пагинацией
    """
    user_id = callback.from_user.id
    
    # Определяем номер страницы
    page = 1
    if callback.data.startswith("prizes_page_"):
        page = int(callback.data.split("_")[2])
    
    # Получаем пользователя из БД
    user_result = await session.execute(
        select(User).where(User.telegram_id == user_id)
    )
    user = user_result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)
        return
    
    # Получаем список призов пользователя
    prizes_result = await session.execute(
        select(Prize.id, Prize.prize_name, Prize.combination, Prize.status, Prize.created_at, Prize.confirmed_at, Prize.used_at, Prize.admin_comment)
        .where(Prize.user_id == user.id)
        .order_by(Prize.created_at.desc())
    )
    prizes = prizes_result.all()
    
    if not prizes:
        await callback.message.edit_text(
            "🏆 <b>Мои призы</b>\n\n"
            "У вас пока нет выигранных призов. Попробуйте сыграть в слот-машину!",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
            ).as_markup(),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Настройки пагинации
    items_per_page = 3
    total_pages = (len(prizes) + items_per_page - 1) // items_per_page
    
    # Проверяем валидность номера страницы
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    # Вычисляем индексы для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(prizes))
    
    # Получаем призы для текущей страницы
    current_page_prizes = prizes[start_idx:end_idx]
    
    # Формируем список призов для клавиатуры
    prizes_data = [(prize.id, prize.prize_name, prize.status) for prize in current_page_prizes]
    
    # Создаем клавиатуру с пагинацией
    keyboard = get_prizes_list_keyboard(prizes_data)
    
    # Добавляем кнопки пагинации
    pagination_row = []
    
    if page > 1:
        pagination_row.append(
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"prizes_page_{page-1}")
        )
    
    pagination_row.append(
        InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="prizes_page_info")
    )
    
    if page < total_pages:
        pagination_row.append(
            InlineKeyboardButton(text="Вперед ▶️", callback_data=f"prizes_page_{page+1}")
        )
    
    # Добавляем строку с пагинацией в клавиатуру
    keyboard.inline_keyboard.append(pagination_row)
    
    # Формируем сообщение
    message_text = (
        "🏆 <b>Мои призы</b>\n\n"
        "Выберите приз для просмотра подробной информации:\n\n"
        "<i>⏳ - ожидает подтверждения\n"
        "✅ - подтвержден\n"
        "❌ - отклонен\n"
        "🎉 - использован</i>"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

# Обработчик просмотра информации о призе
@router.callback_query(F.data.startswith("show_prize_"))
async def show_prize_info(
    callback: CallbackQuery, 
    session: AsyncSession
):
    """
    Показывает информацию о конкретном призе
    """
    # Извлекаем ID приза из callback_data
    prize_id = int(callback.data.split("_")[2])
    
    # Получаем информацию о призе
    prize_result = await session.execute(
        select(Prize).where(Prize.id == prize_id)
    )
    prize = prize_result.scalar_one_or_none()
    
    if not prize:
        await callback.answer("Приз не найден.", show_alert=True)
        return
    
    # Получаем информацию о пользователе
    user_result = await session.execute(
        select(User).where(User.id == prize.user_id)
    )
    user = user_result.scalar_one_or_none()
    
    if not user or user.telegram_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому призу.", show_alert=True)
        return
    
    # Определяем статус и эмодзи
    status_info = {
        "PENDING": {
            "emoji": "⏳",
            "text": "Ожидает подтверждения",
            "description": "Администратор проверяет ваш выигрыш"
        },
        "CONFIRMED": {
            "emoji": "✅",
            "text": "Подтвержден",
            "description": "Приз готов к получению"
        },
        "REJECTED": {
            "emoji": "❌",
            "text": "Отклонен",
            "description": "Приз не подтвержден администратором"
        },
        "USED": {
            "emoji": "🎉",
            "text": "Использован",
            "description": "Приз был успешно получен"
        }
    }.get(prize.status, {
        "emoji": "❓",
        "text": "Неизвестный статус",
        "description": ""
    })
    
    # Формируем сообщение с информацией о призе
    message_text = (
        f"{status_info['emoji']} <b>Информация о призе #{prize.id}</b>\n\n"
        f"🎁 <b>Приз:</b> {prize.prize_name}\n"
        f"🎰 <b>Выигрышная комбинация:</b>\n{prize.combination}\n"
        f"📅 <b>Дата выигрыша:</b> {prize.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📊 <b>Статус:</b> {status_info['text']}\n"
        f"ℹ️ <i>{status_info['description']}</i>\n"
    )
    
    # Добавляем информацию о подтверждении/отклонении
    if prize.status in ["CONFIRMED", "REJECTED"]:
        message_text += f"\n📝 <b>Дата {status_info['text'].lower()}:</b> {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        if prize.status == "CONFIRMED":
            message_text += (
                "\n🏆 <b>Как получить приз:</b>\n"
                "1. Обратитесь в наш автосервис\n"
                "2. Адрес: <b>ул.Калинина 128А к2</b>\n"
                "3. При себе иметь документ, удостоверяющий личность\n"
                "\n⏰ <i>Приз действителен в течение 30 дней</i>"
            )
        elif prize.status == "REJECTED":
            reject_reason = getattr(prize, 'reject_reason', None) or prize.admin_comment or "Причина не указана"
            message_text += f"\n❗️ <b>Причина отклонения:</b>\n{reject_reason}\n"
    
    # Добавляем комментарий администратора, если есть
    if prize.admin_comment and prize.status != "REJECTED":
        message_text += f"\n👨‍💼 <b>Комментарий администратора:</b>\n{prize.admin_comment}\n"
    
    # Создаем клавиатуру
    keyboard = []
    
    # Добавляем кнопку связи с администратором для подтвержденных призов
    if prize.status == "CONFIRMED":
        keyboard.append([
            InlineKeyboardButton(
                text="💬 Связаться с администратором",
                url="https://t.me/Juli_Shriman"
            )
        ])
        
        # Добавляем кнопку для отметки приза как использованного (только для админов)
        if callback.from_user.id in settings.admin_ids:
            keyboard.append([
                InlineKeyboardButton(
                    text="🎉 Отметить как выданный",
                    callback_data=f"mark_prize_used_{prize.id}"
                )
            ])
    
    # Добавляем кнопку "Назад"
    keyboard.append([
        InlineKeyboardButton(
            text="🔙 К списку призов",
            callback_data="my_prizes"
        )
    ])
    
    await callback.message.edit_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )

# Обработчик команды подтверждения приза (для администраторов)
@router.message(Command("confirm_prize"))
async def cmd_confirm_prize(
    message: Message, 
    session: AsyncSession,
    bot: Bot,
    user: User
):
    """
    Подтверждает приз и отправляет уведомление пользователю
    """
    # Проверяем, что пользователь - администратор
    if not user.is_admin:
        return
    
    # Извлекаем ID приза из сообщения
    command_parts = message.text.split()
    if len(command_parts) < 2:
        await message.answer(
            "❌ <b>Ошибка:</b> Укажите ID приза.\n"
            "Пример: <code>/confirm_prize 123</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        prize_id = int(command_parts[1])
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка:</b> ID приза должен быть числом.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем информацию о призе
    prize_result = await session.execute(
        select(Prize).where(Prize.id == prize_id)
    )
    prize = prize_result.scalar_one_or_none()
    
    if not prize:
        await message.answer(
            f"❌ <b>Ошибка:</b> Приз с ID {prize_id} не найден.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем, не подтвержден ли уже приз
    if prize.status != "PENDING":
        await message.answer(
            f"❌ <b>Ошибка:</b> Приз с ID {prize_id} уже имеет статус {prize.status}.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем информацию о пользователе
    user_result = await session.execute(
        select(User).where(User.id == prize.user_id)
    )
    winner = user_result.scalar_one_or_none()
    
    if not winner:
        await message.answer(
            f"❌ <b>Ошибка:</b> Пользователь, выигравший приз, не найден.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Извлекаем комментарий администратора, если есть
    admin_comment = None
    if len(command_parts) > 2:
        admin_comment = " ".join(command_parts[2:])
    
    # Обновляем статус приза
    prize.status = "CONFIRMED"
    prize.confirmed_at = datetime.now()
    if admin_comment:
        prize.admin_comment = admin_comment
    
    await session.commit()
    
    # Отправляем уведомление пользователю
    user_notification = (
        f"🎉 <b>Ваш приз подтвержден!</b>\n\n"
        f"<b>Приз:</b> {prize.prize_name}\n"
        f"<b>Выигрышная комбинация:</b> {prize.combination}\n\n"
        f"<b>Для получения приза:</b>\n"
        f"Обратитесь в наш автосервис по адресу: <b>ул.Калинина 128А к2</b>\n"
        f"При себе иметь документ, удостоверяющий личность.\n\n"
    )
    
    # Добавляем комментарий администратора, если есть
    if admin_comment:
        user_notification += f"<b>Комментарий администратора:</b>\n{admin_comment}\n\n"
    
    user_notification += "Если у вас возникли вопросы, обратитесь к администратору."
    
    try:
        await bot.send_message(
            chat_id=winner.telegram_id,
            text=user_notification,
            parse_mode=ParseMode.HTML
        )
        
        await message.answer(
            f"✅ <b>Приз успешно подтвержден!</b>\n\n"
            f"Уведомление отправлено пользователю {winner.full_name}.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {winner.telegram_id}: {e}")
        await message.answer(
            f"⚠️ <b>Приз подтвержден, но возникла ошибка при отправке уведомления пользователю.</b>\n"
            f"Ошибка: {str(e)}",
            parse_mode=ParseMode.HTML
        )

# Обработчик команды отправки уведомления о получении приза
@router.message(Command("notify_prize"))
async def cmd_notify_prize(
    message: Message, 
    session: AsyncSession,
    bot: Bot,
    user: User
):
    """
    Отправляет уведомление пользователю о необходимости явиться для получения приза
    """
    # Проверяем, что пользователь - администратор
    if not user.is_admin:
        return
    
    # Извлекаем ID приза и текст уведомления из сообщения
    command_parts = message.text.split(maxsplit=2)
    if len(command_parts) < 3:
        await message.answer(
            "❌ <b>Ошибка:</b> Укажите ID приза и текст уведомления.\n"
            "Пример: <code>/notify_prize 123 Приходите завтра с 10:00 до 18:00</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        prize_id = int(command_parts[1])
        notification_text = command_parts[2]
    except (ValueError, IndexError):
        await message.answer(
            "❌ <b>Ошибка:</b> Неверный формат команды.\n"
            "Пример: <code>/notify_prize 123 Приходите завтра с 10:00 до 18:00</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем информацию о призе
    prize_result = await session.execute(
        select(Prize).where(Prize.id == prize_id)
    )
    prize = prize_result.scalar_one_or_none()
    
    if not prize:
        await message.answer(
            f"❌ <b>Ошибка:</b> Приз с ID {prize_id} не найден.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем статус приза
    if prize.status != "CONFIRMED":
        await message.answer(
            f"❌ <b>Ошибка:</b> Приз с ID {prize_id} имеет статус {prize.status}. "
            f"Отправлять уведомления можно только для подтвержденных призов.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем информацию о пользователе
    user_result = await session.execute(
        select(User).where(User.id == prize.user_id)
    )
    winner = user_result.scalar_one_or_none()
    
    if not winner:
        await message.answer(
            f"❌ <b>Ошибка:</b> Пользователь, выигравший приз, не найден.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Обновляем комментарий администратора
    prize.admin_comment = notification_text
    await session.commit()
    
    # Отправляем уведомление пользователю
    user_notification = (
        f"🔔 <b>Уведомление о получении приза</b>\n\n"
        f"<b>Приз:</b> {prize.prize_name}\n\n"
        f"<b>Сообщение от администратора:</b>\n{notification_text}\n\n"
        f"<b>Адрес автосервиса:</b> ул. Примерная, 123\n"
        f"<b>При себе иметь:</b> документ, удостоверяющий личность\n\n"
        f"Если у вас возникли вопросы, обратитесь к администратору."
    )
    
    try:
        await bot.send_message(
            chat_id=winner.telegram_id,
            text=user_notification,
            parse_mode=ParseMode.HTML
        )
        
        await message.answer(
            f"✅ <b>Уведомление успешно отправлено пользователю {winner.full_name}!</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {winner.telegram_id}: {e}")
        await message.answer(
            f"⚠️ <b>Возникла ошибка при отправке уведомления пользователю.</b>\n"
            f"Ошибка: {str(e)}",
            parse_mode=ParseMode.HTML
        )

# Обработчик просмотра статистики рефералов
@router.callback_query(F.data == "show_referrals")
async def show_referrals(
    callback: CallbackQuery, 
    session: AsyncSession,
    bot: Bot
):
    """
    Показывает информацию о рефералах пользователя
    """
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Получаем статистику по рефералам
    invited_count, attempts_from_referrals = await get_referral_stats(user_id, session)
    
    # Генерируем реферальную ссылку
    ref_link = await generate_referral_link(user_id, bot)
    
    # Формируем сообщение с информацией о рефералах
    message_text = (
        "<b>📊 Ваша реферальная статистика</b>\n\n"
        f"<b>Приглашено друзей:</b> {invited_count}\n"
        f"<b>Получено дополнительных попыток:</b> {attempts_from_referrals}\n\n"
        "<i>Ваша реферальная ссылка:</i>\n"
        f"<code>{ref_link}</code>\n\n"
        "<i>Приглашайте друзей и получайте дополнительные попытки в слот-машине!</i>"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        ).as_markup(),
        parse_mode=ParseMode.HTML
    )

# Обработчик показа правил
@router.callback_query(F.data == "slot_rules")
async def show_rules(callback: CallbackQuery):
    """
    Показывает правила слот-машины
    """
    await callback.answer()
    
    message_text = (
        "<b>❓ Правила слот-машины</b>\n\n"
        "<b>Как играть:</b>\n"
        "• Нажмите кнопку «Крутить барабан» для запуска\n"
        "• Каждый день вы получаете <b>2 базовые попытки</b>\n"
        "• Дополнительные попытки можно получить, <b>приглашая друзей</b>\n\n"
        "<b>Призы:</b>\n"
        "• <b>💎💎💎</b> — Сертификат на ремонт 1500₽\n"
        "• <b>🎉🎉🎉</b> — Скидка 10% на тонировку\n"
        "• <b>🛢️🛢️🛢️</b> — Бесплатная замена масла\n"
        "• <b>🚗🚗🚗</b> — Полировка фар в подарок\n" 
        "• <b>🎁🎁🎁</b> — Подарочный сертификат на 500₽\n"
        "• <b>🍒🍒🍒</b> — 2 дополнительные попытки\n\n"
        "<i>При выпадении двух или более 🍒 вы получаете +1 дополнительную попытку</i>"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        ).as_markup(),
        parse_mode=ParseMode.HTML
    )

# Обработчик кнопки "Назад"
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, session: AsyncSession):
    """
    Возвращает пользователя в главное меню слот-машины
    """
    await callback.answer()
    
    # Получаем пользователя из БД
    result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    user = result.scalar_one_or_none()
    
    await callback.message.edit_text(
        "🎰 <b>Слот-машина ILPO-TON</b>\n\n"
        "<i>Испытайте удачу и выиграйте ценные призы!</i>\n\n"
        f"<b>Доступно попыток:</b> {user.attempts if user else 1}\n\n"
        "<b>Правила:</b>\n"
        "• 3 одинаковых символа = <b>приз</b>\n"
        "• 2 или более 🍒 = <b>дополнительная попытка</b>\n"
        "• Базовая попытка: <b>2 раза в день</b>\n"
        "• Дополнительные попытки за <b>приглашенных друзей</b>",
        reply_markup=get_slot_machine_keyboard(),
        parse_mode=ParseMode.HTML
    )

# Обработчик кнопки "Пригласить друзей"
@router.callback_query(F.data == "invite_friends")
async def invite_friends(
    callback: CallbackQuery, 
    session: AsyncSession,
    bot: Bot
):
    """
    Создаёт сообщение для приглашения друзей с кнопкой "Поделиться", которая позволяет
    выбрать контакты для приглашения
    """
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Получаем пользователя из БД
    result = await session.execute(
        select(User).where(User.telegram_id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.message.edit_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=get_slot_machine_keyboard()
        )
        return
    
    # Генерируем реферальную ссылку
    ref_link = await generate_referral_link(user_id, bot)
    
    # Создаем новое сообщение с кнопкой для выбора пользователей
    invite_message = (
        "<b>🎰 Приглашение в ILPO-TON Бот</b>\n\n"
        "<i>Привет! Я использую бот ILPO-TON с крутой слот-машиной и приятными бонусами.</i>\n\n"
        "<b>Переходи по ссылке и получи +2 бонусные попытки в слот-машине!</b>"
    )
    
    # Отправляем новое сообщение с кнопкой
    await callback.message.edit_text(
        "<b>👥 Пригласите друзей в ILPO-TON Бот</b>\n\n"
        "<i>Нажмите кнопку ниже, чтобы выбрать контакты для приглашения.\n"
        "За каждого присоединившегося друга вы получите +2 попытки в слот-машине!</i>",
        reply_markup=InlineKeyboardBuilder()
            .row(InlineKeyboardButton(
                text="📤 Поделиться с друзьями", 
                switch_inline_query=f"Привет! Переходи в бот ILPO-TON и получай призы в слот-машине: {ref_link}"
            ))
            .row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
            .as_markup(),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("confirm_slot_prize_"))
async def confirm_slot_prize(callback: CallbackQuery, session: AsyncSession, bot: Bot, user: User):
    """
    Подтверждает приз через inline кнопку
    """
    try:
        # Проверяем, что пользователь - администратор
        if not user.is_admin or callback.from_user.id not in settings.admin_ids:
            logger.warning(f"Попытка подтверждения приза неадминистратором: user_id={callback.from_user.id}, is_admin={user.is_admin}")
            await callback.answer("❌ У вас нет прав для подтверждения призов", show_alert=True)
            return
        
        # Извлекаем ID приза из callback_data
        prize_id = int(callback.data.split("_")[3])
        
        # Получаем информацию о призе с блокировкой строки
        # FOR UPDATE блокирует строку от изменений другими транзакциями
        prize_result = await session.execute(
            select(Prize)
            .where(Prize.id == prize_id)
            .with_for_update(skip_locked=True)  # skip_locked=True позволяет пропустить уже заблокированные строки
        )
        prize = prize_result.scalar_one_or_none()
        
        if not prize:
            await callback.answer("❌ Приз не найден или уже обрабатывается другим администратором", show_alert=True)
            return
        
        # Проверяем, не подтвержден ли уже приз
        if prize.status != "PENDING":
            # Если приз уже подтвержден, получаем информацию о том, кто подтвердил
            if prize.confirmed_by:
                confirming_admin_result = await session.execute(
                    select(User).where(User.id == prize.confirmed_by)
                )
                confirming_admin = confirming_admin_result.scalar_one_or_none()
                admin_name = confirming_admin.full_name if confirming_admin else "Другой администратор"
                
                await callback.answer(
                    f"❌ Приз уже {prize.status.lower()} администратором {admin_name} "
                    f"({prize.confirmed_at.strftime('%d.%m.%Y %H:%M')})",
                    show_alert=True
                )
            else:
                await callback.answer(f"❌ Приз уже имеет статус {prize.status}", show_alert=True)
            return
        
        # Получаем информацию о победителе
        winner_result = await session.execute(
            select(User).where(User.id == prize.user_id)
        )
        winner = winner_result.scalar_one_or_none()
        
        if not winner:
            await callback.answer("❌ Пользователь, выигравший приз, не найден", show_alert=True)
            return
        
        # Обновляем статус приза
        prize.status = "CONFIRMED"
        prize.confirmed_at = datetime.now()
        prize.confirmed_by = user.id  # ID администратора, подтвердившего приз
        
        try:
            await session.commit()
        except Exception as e:
            logger.error(f"Ошибка при сохранении подтверждения приза: {e}")
            await session.rollback()
            await callback.answer("❌ Не удалось подтвердить приз. Попробуйте еще раз", show_alert=True)
            return
        
        # Отправляем уведомление пользователю
        user_notification = (
            f"🎉 <b>Ваш приз подтвержден!</b>\n\n"
            f"<b>Приз:</b> {prize.prize_name}\n"
            f"<b>Выигрышная комбинация:</b> {prize.combination}\n\n"
            f"<b>Для получения приза:</b>\n"
            f"Обратитесь в наш автосервис по адресу: <b>ул.Калинина 128А к2</b>\n"
            f"При себе иметь документ, удостоверяющий личность.\n\n"
            f"<i>Приз действителен в течение 30 дней.</i>"
        )
        
        try:
            await bot.send_message(
                chat_id=winner.telegram_id,
                text=user_notification,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления победителю: {e}")
            # Не прерываем процесс, так как приз уже подтвержден
        
        # Обновляем сообщение администратора
        admin_notification = (
            f"✅ <b>Приз подтвержден!</b>\n\n"
            f"👤 Игрок: {winner.full_name}\n"
            f"🆔 ID: {winner.telegram_id}\n"
            f"🎁 Приз: {prize.prize_name}\n"
            f"🎰 Комбинация: {prize.combination}\n"
            f"📅 Подтверждено: {prize.confirmed_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"👨‍💼 Подтвердил: {user.full_name}"
        )
        
        # Обновляем сообщение с новой клавиатурой
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать победителю",
                    url=f"tg://user?id={winner.telegram_id}"
                )
            ]
        ])
        
        # Обновляем все сообщения с этим призом у всех администраторов
        for admin_id in settings.admin_ids:
            try:
                # Пытаемся обновить сообщение у каждого администратора
                await bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=callback.message.message_id,
                    text=admin_notification,
                    reply_markup=admin_keyboard,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении сообщения у администратора {admin_id}: {e}")
                continue
        
        await callback.answer("✅ Приз успешно подтвержден!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка при подтверждении приза: {e}")
        await callback.answer("❌ Произошла ошибка при подтверждении приза", show_alert=True)
        await session.rollback()  # Откатываем транзакцию в случае ошибки

"""
Клавиатуры для слот-машины
"""

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardButton, KeyboardButton
from core.utils.subscription import CHANNEL_ID

def get_slot_machine_keyboard():
    """
    Клавиатура с кнопкой запуска слот-машины
    
    Returns:
        InlineKeyboardBuilder: Клавиатура
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🎰 Крутить барабан", callback_data="spin_slot")
    )
    
    builder.row(
        InlineKeyboardButton(text="📊 Мои рефералы", callback_data="show_referrals"),
        InlineKeyboardButton(text="❓ Правила", callback_data="slot_rules")
    )
    
    builder.row(
        InlineKeyboardButton(text="🏆 Мои призы", callback_data="my_prizes")
    )
    
    builder.row(
        InlineKeyboardButton(text="👥 Пригласить друзей", callback_data="invite_friends")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_main")
    )
    
    return builder.as_markup()

def get_main_menu_with_slots_button():
    """
    Добавляет кнопку слот-машины в главное меню
    
    Returns:
        ReplyKeyboardBuilder: Клавиатура
    """
    builder = ReplyKeyboardBuilder()
    
    # Основные кнопки меню (предполагается, что они уже существуют в других модулях)
    builder.row(
        KeyboardButton(text="🎰 Слот-машина")
    )
    
    return builder.as_markup(resize_keyboard=True)

def get_subscription_keyboard(channel_name: str):
    """
    Клавиатура с кнопкой подписки на канал
    
    Args:
        channel_name: Название канала
        
    Returns:
        InlineKeyboardBuilder: Клавиатура
    """
    builder = InlineKeyboardBuilder()
    
    # Используем правильный URL-адрес канала без символа @
    channel_url = "https://t.me/" + CHANNEL_ID.replace("@", "")
    
    builder.row(
        InlineKeyboardButton(text=f"📢 Подписаться на {channel_name}", url=channel_url)
    )
    
    builder.row(
        InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")
    )
    
    return builder.as_markup()

def get_prize_keyboard(prize_id: int):
    """
    Клавиатура для управления призом
    
    Args:
        prize_id: ID приза
        
    Returns:
        InlineKeyboardBuilder: Клавиатура
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📋 Информация о призе", callback_data=f"prize_info_{prize_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Назад к призам", callback_data="my_prizes")
    )
    
    return builder.as_markup()

def get_prizes_list_keyboard(prizes_data):
    """
    Клавиатура со списком призов пользователя
    
    Args:
        prizes_data: Список призов [(id, name, status), ...]
        
    Returns:
        InlineKeyboardBuilder: Клавиатура
    """
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для каждого приза
    for prize_id, prize_name, status in prizes_data:
        # Добавляем статус к названию приза
        status_emoji = {
            "PENDING": "⏳",
            "CONFIRMED": "✅",
            "REJECTED": "❌",
            "USED": "🎉"
        }.get(status, "❓")
        
        builder.row(
            InlineKeyboardButton(text=f"{status_emoji} {prize_name}", callback_data=f"show_prize_{prize_id}")
        )
    
    # Кнопка возврата в меню
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
    )
    
    return builder.as_markup()

def get_win_celebration_keyboard(prize_id: int):
    """
    Клавиатура для сообщения о выигрыше
    
    Args:
        prize_id: ID приза
        
    Returns:
        InlineKeyboardBuilder: Клавиатура
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🏆 Информация о призе", callback_data=f"show_prize_{prize_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="🎰 Играть снова", callback_data="spin_slot"),
        InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")
    )
    
    return builder.as_markup() 
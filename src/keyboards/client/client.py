# src/keyboards/client/client.py

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from datetime import datetime

from database.models import TimeSlot, Service

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Главная клавиатура
    """
    keyboard = [
        [
            KeyboardButton(text="📝 Записаться"),
        ],
        [
            KeyboardButton(text="💰 Услуги и цены"),
            KeyboardButton(text="📢 Новости")
        ],
        [
            KeyboardButton(text="👤 Личный кабинет"),
            KeyboardButton(text="ℹ️ Помощь")
        ],
        [
            KeyboardButton(text="🎰 Слот-машина")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_contact_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для отправки контакта
    """
    keyboard = [[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_services_keyboard(services: List[Service]) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру со списком услуг
    """
    keyboard = []
    
    # Добавляем кнопки для каждой услуги
    for service in services:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{service.name} - от {service.price}₽",
                callback_data=f"appointment_select_service_{service.id}"
            )
        ])
    
    # # Добавляем кнопку возврата в главное меню
    # keyboard.append([
    #     InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")
    # ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_time_slots_keyboard(time_slots: List[TimeSlot], page: int = 1) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с доступными временными слотами
    С пагинацией по 6 слотов на странице (2 столбца по 3 кнопки)
    """
    keyboard = []
    
    # Фильтруем слоты, начиная с текущей даты
    current_date = datetime.now().date()
    filtered_slots = [slot for slot in time_slots if slot.date.date() >= current_date and slot.is_available]
    
    # Группируем слоты по датам
    dates = {}
    for slot in filtered_slots:
        date_str = slot.date.strftime('%d.%m.%Y')
        slot_date = slot.date.date()
        if date_str not in dates:
            dates[date_str] = {'slots': [slot], 'date': slot_date}
        else:
            dates[date_str]['slots'].append(slot)
    
    # Сортируем даты по возрастанию
    sorted_dates = sorted(dates.items(), key=lambda x: x[1]['date'])
    
    # Настройки пагинации
    items_per_page = 6  # 2 столбца по 3 кнопки
    total_pages = (len(sorted_dates) + items_per_page - 1) // items_per_page
    
    # Проверяем валидность номера страницы
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages if total_pages > 0 else 1
    
    # Вычисляем индексы для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(sorted_dates))
    
    # Добавляем кнопки с датами для текущей страницы
    current_page_dates = sorted_dates[start_idx:end_idx]
    temp_row = []
    
    for date_str, date_info in current_page_dates:
        slots = date_info['slots']
        earliest_slot = min(slots, key=lambda x: x.date.time())
        latest_slot = max(slots, key=lambda x: x.date.time())
        time_range = f"{earliest_slot.date.strftime('%H:%M')}-{latest_slot.date.strftime('%H:%M')}"
        
        button = InlineKeyboardButton(
            text=f"📅 {date_str}\n({time_range}, {len(slots)} сл.)",
            callback_data=f"select_date_{date_str}"
        )
        temp_row.append(button)
        
        # Если в строке 2 кнопки или это последняя дата, добавляем строку в клавиатуру
        if len(temp_row) == 2 or date_str == current_page_dates[-1][0]:
            keyboard.append(temp_row)
            temp_row = []
    
    # Добавляем кнопки навигации
    nav_buttons = []
    
    if total_pages > 1:
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"client_date_page_{page-1}"
            ))
            
        nav_buttons.append(InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}",
            callback_data="ignore"
        ))
        
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"client_date_page_{page+1}"
            ))
            
        keyboard.append(nav_buttons)
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_time_slots_for_date_keyboard(time_slots: List[TimeSlot], date_str: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с временными слотами для конкретной даты
    """
    keyboard = []
    
    # Фильтруем и сортируем слоты для выбранной даты
    date_slots = [
        slot for slot in time_slots 
        if slot.date.strftime('%d.%m.%Y') == date_str and slot.is_available
    ]
    date_slots.sort(key=lambda x: x.date.time())
    
    # Добавляем временные слоты
    for slot in date_slots:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🕐 {slot.date.strftime('%H:%M')}",
                callback_data=f"select_time_{slot.id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="↩️ Назад к датам", callback_data="client_back_to_dates")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_profile_keyboard(has_active_appointments: bool = False) -> InlineKeyboardMarkup:
    """
    Клавиатура личного кабинета
    """
    keyboard = [
        [InlineKeyboardButton(text="📋 История записей", callback_data="appointments_history")],
        [InlineKeyboardButton(text="📱 Изменить контакт", callback_data="change_contact")]
    ]
    if has_active_appointments:
        keyboard.insert(0, [
            InlineKeyboardButton(text="🕐 Активные записи", callback_data="active_appointments")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard) 
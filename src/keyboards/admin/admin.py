# src/keyboards/admin/admin.py

from typing import List
from datetime import datetime

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging

logger = logging.getLogger(__name__)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает основную клавиатуру администратора (Reply клавиатура)
    Используется только для главного меню
    """
    keyboard = [
        [
            KeyboardButton(text="🔙 Пользовательский режим"),
            KeyboardButton(text="👨‍💼 Панель администратора")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_admin_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Создает inline-клавиатуру для админ-панели
    Используется для всех действий администратора
    """
    keyboard = [
        [
            InlineKeyboardButton(text="📝 Управление записями", callback_data="manage_appointments"),
            InlineKeyboardButton(text="🕐 Управление расписанием", callback_data="manage_schedule")
        ],
        [
            InlineKeyboardButton(text="💰 Управление услугами", callback_data="manage_services"),
            InlineKeyboardButton(text="📢 Управление контентом", callback_data="manage_content")
        ],
        [   
            InlineKeyboardButton(text="💰 Запросы на расчет", callback_data="manage_price_requests"),
            InlineKeyboardButton(text="🎰 Слот-машина", callback_data="admin_slot_machine_menu")
        ],
        [
            InlineKeyboardButton(text="🔙 Выйти из Админки", callback_data="exit_admin_panel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_services_management_keyboard(services: list) -> InlineKeyboardMarkup:
    """
    Клавиатура управления услугами
    """
    keyboard = [
        [InlineKeyboardButton(text="📋 Все услуги", callback_data="view_all_services")],
        [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="add_service")],
        [InlineKeyboardButton(text="📁 Архив услуг", callback_data="view_archived_services")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_service_view_keyboard(service_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для просмотра услуги
    """
    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_service_{service_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_service_{service_id}")
        ],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_time_slots_dates_keyboard(time_slots: list, page: int = 1) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с уникальными датами, на которые есть слоты
    С пагинацией по 6 дат на странице (2 столбца по 3 кнопки)
    """
    keyboard = []
    
    # Фильтруем слоты, начиная с текущей даты
    current_date = datetime.now().date()
    filtered_slots = [slot for slot in time_slots if slot.date.date() >= current_date]
    
    # Группируем слоты по датам и сортируем их
    dates = {}
    for slot in filtered_slots:
        date_str = slot.date.strftime('%d.%m.%Y')
        slot_date = slot.date.date()  # Сохраняем дату для сортировки
        if date_str not in dates:
            dates[date_str] = {'count': 1, 'date': slot_date}
        else:
            dates[date_str]['count'] += 1
    
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
        callback_data = f"view_date_{date_str}"
        button = InlineKeyboardButton(
            text=f"📅 {date_str}\n({date_info['count']} сл.)",
            callback_data=callback_data
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
                callback_data=f"date_page_{page-1}"
            ))
            
        nav_buttons.append(InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}",
            callback_data="ignore"
        ))
        
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"date_page_{page+1}"
            ))
            
        keyboard.append(nav_buttons)
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_admin")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_time_slots_for_date_keyboard(time_slots: list, date_str: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с временными слотами для конкретной даты
    """
    keyboard = []
    
    # Добавляем временные слоты
    for slot in time_slots:
        if slot.date.strftime('%d.%m.%Y') == date_str:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🕐 {slot.date.strftime('%H:%M')}",
                    callback_data=f"view_slot_{slot.id}"
                ),
                InlineKeyboardButton(
                    text="❌",
                    callback_data=f"delete_slot_{slot.id}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton(text="↩️ Назад к датам", callback_data="admin_back_to_dates")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_appointments_management_keyboard(appointments: list) -> InlineKeyboardMarkup:
    """
    Клавиатура управления записями
    """
    keyboard = []
    for appointment in appointments:
        keyboard.extend([
            [
                InlineKeyboardButton(
                    text=(
                        f"{appointment.user.full_name} - "
                        f"{appointment.service.name} - "
                        f"{appointment.appointment_time.strftime('%d.%m.%Y %H:%M')}"
                    ),
                    callback_data=f"appointment_{appointment.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm_appointment_{appointment.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_appointment_{appointment.id}"
                )
            ]
        ])
    
    keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_news_management_keyboard(news_items: list) -> InlineKeyboardMarkup:
    """
    Клавиатура управления новостями
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="➕ Добавить новую публикацию",
                callback_data="content_add_news_"
            )
        ]
    ]
    
    if news_items:
        keyboard.append([
            InlineKeyboardButton(
                text="📰 Список публикаций",
                callback_data="news_divider"
            )
        ])
        
        # Добавляем новости с датами (не более 5)
        for item in news_items[:5]:
            # Форматируем дату
            date_str = item.created_at.strftime("%d.%m.%Y")
            # Обрезаем заголовок если он слишком длинный
            title = item.title if len(item.title) <= 30 else f"{item.title[:27]}..."
            # Добавляем кнопку новости
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📌 {date_str} | {title}",
                    callback_data=f"content_news_{item.id}"
                )
            ])
    
    keyboard.append([
        InlineKeyboardButton(
            text="↩️ Вернуться назад",
            callback_data="content_back_to_content"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_content_management_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура управления контентом
    """
    keyboard = [
        [
            InlineKeyboardButton(text="📢 Управление новостями", callback_data="content_manage_news"),
            InlineKeyboardButton(text="📨 Управление рассылками", callback_data="content_manage_broadcasts")
        ],
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_admin")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_broadcast_management_keyboard(broadcasts: list = None) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру для управления рассылками
    """
    keyboard = [
        [
            InlineKeyboardButton(text="📝 Создать новую рассылку", callback_data="broadcast_add")
        ]
    ]
    
    if broadcasts:
        for broadcast in broadcasts[:5]:  # Ограничиваем количество отображаемых рассылок
            status_emoji = {
                "DRAFT": "📝",
                "SENDING": "🔄",
                "SENT": "✅",
                "CANCELLED": "❌"
            }.get(broadcast.status, "❓")
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status_emoji} {broadcast.title[:30]}...",
                    callback_data=f"broadcast_view_{broadcast.id}"
                )
            ])
    
    keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast_back_to_content")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_broadcast_audience_keyboard() -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру для выбора аудитории рассылки
    """
    keyboard = [
        [
            InlineKeyboardButton(text="👥 Все пользователи", callback_data="broadcast_audience_all"),
            InlineKeyboardButton(text="👤 Активные клиенты", callback_data="broadcast_audience_active")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
        ]
    ]
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_skip_image_keyboard() -> ReplyKeyboardMarkup:
    """
    Возвращает клавиатуру с кнопкой "Пропустить" для пропуска загрузки изображения
    """
    keyboard = [
        [KeyboardButton(text="Пропустить")]
    ]
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для подтверждения действия
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="✅ Да, подтвердить",
        callback_data=action
    )
    
    builder.button(
        text="❌ Отмена",
        callback_data="cancel_action"
    )
    
    # Располагаем кнопки в один ряд
    builder.adjust(2)
    return builder.as_markup()


def get_service_edit_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора поля для редактирования услуги
    """
    keyboard = [
        [
            InlineKeyboardButton(text="📝 Название", callback_data="edit_field_name"),
            InlineKeyboardButton(text="📋 Описание", callback_data="edit_field_description")
        ],
        [
            InlineKeyboardButton(text="💰 Стоимость", callback_data="edit_field_price"),
            InlineKeyboardButton(text="⏱ Длительность", callback_data="edit_field_duration")
        ],
        [
            InlineKeyboardButton(text="🖼 Изображение", callback_data="edit_field_image")
        ],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_edit_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопкой возврата к редактированию
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад к редактированию", callback_data="back_to_service_edit")]
    ]) 
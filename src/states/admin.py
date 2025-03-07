# src/states/admin.py

from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    """Базовые состояния администратора"""
    viewing_panel = State()  # Просмотр панели администратора
    confirming_action = State()  # Подтверждение действия


class ServiceStates(StatesGroup):
    """Состояния для управления услугами"""
    # Состояния для добавления новой услуги
    adding_name = State()        # Ввод названия новой услуги
    adding_description = State() # Ввод описания новой услуги
    adding_price = State()      # Ввод стоимости новой услуги
    adding_duration = State()   # Ввод длительности новой услуги
    
    # Состояния для редактирования существующей услуги
    entering_name = State()     # Ввод названия при редактировании
    entering_description = State() # Ввод описания при редактировании
    entering_price = State()    # Ввод стоимости при редактировании
    entering_duration = State() # Ввод длительности при редактировании
    editing = State()           # Редактирование услуги
    uploading_photo = State()      # Загрузка фото для услуги
    editing_field = State()        # Редактирование поля услуги


class TimeSlotStates(StatesGroup):
    """Состояния для управления временными слотами"""
    selecting_date = State()        # Выбор даты
    selecting_time = State()        # Выбор времени
    selecting_auto_month = State()  # Новое состояние для выбора месяца автосоздания
    adding_comment = State()        # Добавление комментария к записи


class AdminAppointmentStates(StatesGroup):
    """Состояния для управления записями администратором"""
    viewing_appointments = State()  # Просмотр списка записей
    viewing_details = State()      # Просмотр деталей записи
    setting_appointment_price = State()  # Установка цены для записи
    setting_admin_response = State()  # Установка ответа администратора
    adding_appointment_comment = State()  # Добавление комментария к записи
    confirming_appointment = State()    # Подтверждение записи
    cancelling_appointment = State()    # Отмена записи
    editing_appointment = State()      # Редактирование записи
    entering_appointment_id = State()  # Ввод ID записи для редактирования
    editing_appointment_field = State()  # Редактирование конкретного поля записи


class ContentStates(StatesGroup):
    """Состояния для управления контентом"""
    entering_title = State()       # Ввод заголовка
    entering_description = State() # Ввод описания
    uploading_photo = State()      # Загрузка фото
    editing = State()              # Редактирование


class NewsStates(StatesGroup):
    """Состояния для управления новостями"""
    # Состояния для создания новости
    entering_title = State()  # Ввод заголовка новости
    entering_content = State()  # Ввод текста новости
    uploading_photo = State()  # Загрузка фото для новости

    # Состояния для редактирования
    edit_title = State()     # Редактирование заголовка
    edit_content = State()   # Редактирование текста
    edit_photo = State()     # Редактирование фото


class PriceRequestStates(StatesGroup):
    """
    Состояния для работы с запросами на расчет стоимости
    """
    waiting_for_response = State()  # Ожидание ответа администратора
    waiting_for_template_params = State()  # Ожидание параметров для шаблона
    editing_response = State()  # Редактирование ответа


class BroadcastStates(StatesGroup):
    """Состояния для управления рассылками"""
    waiting_for_title = State()  # Ожидание ввода заголовка рассылки
    waiting_for_content = State()  # Ожидание ввода текста рассылки
    waiting_for_image = State()  # Ожидание загрузки изображения
    waiting_for_audience = State()  # Ожидание выбора аудитории
    confirming_send = State()       # Подтверждение отправки рассылки
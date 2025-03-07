# src/states/client.py

from aiogram.fsm.state import State, StatesGroup


class AppointmentStates(StatesGroup):
    """Состояния для процесса записи"""
    selecting_date = State()        # Выбор даты
    selecting_time = State()        # Выбор времени
    selecting_service = State()     # Выбор услуги
    entering_car_brand = State()    # Ввод марки авто
    entering_car_model = State()    # Ввод модели авто
    entering_car_year = State()     # Ввод года выпуска
    entering_comment = State()      # Ввод комментария
    canceling_appointment = State()  # Новое состояние для отмены записи
    entering_cancel_reason = State()  # Ввод причины отмены
    confirming = State()           # Подтверждение записи


class ProfileStates(StatesGroup):
    """Состояния для профиля пользователя"""
    changing_contact = State()    # Изменение контактных данных
    entering_phone = State()      # Ручной ввод номера телефона


class ServiceStates(StatesGroup):
    """
    Состояния для работы с услугами
    """
    waiting_for_service = State()
    waiting_for_car_info = State()  # Ожидание информации об автомобиле 
    waiting_for_question_choice = State()  # Ожидание выбора вопроса
    waiting_for_question = State()  # Ожидание вопроса

class ClientStates(StatesGroup):
    """Состояния для клиентских операций"""
    waiting_for_cancel_reason = State()  # Ожидание причины отмены записи 

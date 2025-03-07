# src/database/models/models.py

from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, ForeignKey, Text, Boolean, Integer, JSON, ARRAY, BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from ..base import Base


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"

    # ID будет автоматически сгенерирован базой данных
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    full_name: Mapped[str] = mapped_column(String(64))
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Поля для реферальной системы и слот-машины
    referrer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)  # ID пригласившего
    invited_count: Mapped[int] = mapped_column(Integer, default=0)  # Количество приглашенных
    attempts: Mapped[int] = mapped_column(Integer, default=2)  # Попытки для слот-машины
    last_slot_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Время последней попытки

    # Отношения
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="user")
    prizes: Mapped[List["Prize"]] = relationship(
        "Prize",
        foreign_keys="[Prize.user_id]",
        back_populates="user"
    )
    
    # Правильное определение самореферентного отношения для рефералов
    referrer = relationship(
        "User",
        primaryjoin="User.referrer_id==User.id",
        remote_side="User.id",
        backref="invited_users",
        foreign_keys=[referrer_id]
    )

    def __str__(self) -> str:
        return f"User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})"


class Service(Base):
    """Модель услуги"""
    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)  # Длительность в минутах
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)  # Флаг архивации
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Путь к изображению на диске
    image_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)   # Telegram file_id
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    # Отношения
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="service")

    def __str__(self) -> str:
        return f"Service(id={self.id}, name={self.name}, price={self.price})"


class TimeSlot(Base):
    """Модель временного слота"""
    __tablename__ = "time_slots"

    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    
    # Связи
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="time_slot")

    def __str__(self) -> str:
        return f"TimeSlot(id={self.id}, date={self.date}, is_available={self.is_available})"


class Appointment(Base):
    """Модель записи на услугу"""
    __tablename__ = "appointments"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id"), nullable=False)
    time_slot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("time_slots.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    car_brand: Mapped[str] = mapped_column(String(100), nullable=True)
    car_model: Mapped[str] = mapped_column(String(100), nullable=True)
    car_year: Mapped[str] = mapped_column(String(4), nullable=True)
    client_comment: Mapped[str] = mapped_column(Text, nullable=True)
    admin_comment: Mapped[str] = mapped_column(Text, nullable=True)
    admin_response: Mapped[str] = mapped_column(Text, nullable=True)  # Ответ администратора клиенту
    admin_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Причина отмены записи
    final_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)  # Флаг отправки уведомления
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Оценка клиента (1-5)
    
    # Связи
    user = relationship("User", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    time_slot = relationship("TimeSlot", back_populates="appointments")

    def __str__(self) -> str:
        return f"Appointment(id={self.id}, user_id={self.user_id}, service_id={self.service_id})"


class News(Base):
    """Модель новостей"""
    __tablename__ = "news"

    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(1500), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    def __str__(self) -> str:
        return f"News(id={self.id}, title={self.title})"


class PriceRequest(Base):
    """Модель запроса на расчет стоимости"""
    __tablename__ = "price_requests"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id"), nullable=False)
    car_info: Mapped[str] = mapped_column(String(200))
    additional_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Дополнительный вопрос от клиента
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, ANSWERED, ARCHIVED
    admin_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Связи
    user = relationship("User", foreign_keys=[user_id], backref="price_requests")
    service = relationship("Service", backref="price_requests")
    admin = relationship("User", foreign_keys=[admin_id])

    def __str__(self) -> str:
        return f"PriceRequest(id={self.id}, user_id={self.user_id}, service_id={self.service_id})"


class Broadcast(Base):
    """Модель рассылки"""
    __tablename__ = "broadcasts"

    id = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    audience_type: Mapped[str] = mapped_column(String, nullable=False)  # 'all' или 'active'
    status: Mapped[str] = mapped_column(String, default="DRAFT")  # DRAFT, SENDING, SENT, CANCELLED
    sent_count: Mapped[int] = mapped_column(Integer, default=0)

    # Отношения
    admin = relationship("User", foreign_keys=[created_by])

    def __str__(self) -> str:
        return f"Broadcast(id={self.id}, title={self.title}, status={self.status})"


class Prize(Base):
    """Модель для хранения выигранных призов"""
    __tablename__ = "prizes"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    prize_name: Mapped[str] = mapped_column(String(200), nullable=False)  # Название приза
    combination: Mapped[str] = mapped_column(String(20), nullable=False)  # Выигрышная комбинация
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, CONFIRMED, USED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Когда админ подтвердил
    confirmed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)  # ID администратора, подтвердившего приз
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Когда приз был использован
    admin_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Комментарий администратора
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Причина отклонения приза
    
    # Связи с явным указанием внешних ключей
    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="prizes"
    )
    confirming_admin = relationship(
        "User",
        foreign_keys=[confirmed_by],
        backref="confirmed_prizes"
    )
    
    def __str__(self) -> str:
        return f"Prize(id={self.id}, user_id={self.user_id}, prize_name={self.prize_name})"


class SlotSpin(Base):
    """Модель для отслеживания всех попыток игры в слот-машину"""
    __tablename__ = "slot_spins"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    combination: Mapped[str] = mapped_column(String(20), nullable=False)  # Выпавшая комбинация
    result: Mapped[str] = mapped_column(String(200), nullable=False)  # Результат (приз, доп. попытка, ничего)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    prize_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("prizes.id"), nullable=True)  # Ссылка на приз, если был выигрыш
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)  # Устанавливаем значение по умолчанию
    
    # Связи
    user = relationship("User", backref="slot_spins")
    prize = relationship("Prize", backref="spin")
    
    def __str__(self) -> str:
        return f"SlotSpin(id={self.id}, user_id={self.user_id}, result={self.result})" 
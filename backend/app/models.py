from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Invitation(Base):
    __tablename__ = "invitations"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[bytes] = mapped_column(LargeBinary(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Driver(Base):
    __tablename__ = "drivers"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Ride(Base):
    __tablename__ = "rides"
    __table_args__ = (UniqueConstraint("rider_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rider_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.user_id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    pickup_latitude: Mapped[float] = mapped_column(Float)
    pickup_longitude: Mapped[float] = mapped_column(Float)
    dropoff_latitude: Mapped[float] = mapped_column(Float)
    dropoff_longitude: Mapped[float] = mapped_column(Float)
    distance_miles: Mapped[float] = mapped_column(Float)
    duration_minutes: Mapped[float] = mapped_column(Float)
    fare_cents: Mapped[int] = mapped_column(Integer)
    tip_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="matched")
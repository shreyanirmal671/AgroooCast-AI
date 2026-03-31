from __future__ import annotations

import os
from datetime import datetime

import bcrypt
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./agrocast_dev.db",
)

engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="farmer")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    crop_type: Mapped[str] = mapped_column(String(80), default="Mixed")
    farm_size_acres: Mapped[float] = mapped_column(Float, default=1.0)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FarmPlot(Base):
    __tablename__ = "farm_plots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    plot_name: Mapped[str] = mapped_column(String(120), default="")
    soil_type: Mapped[str] = mapped_column(String(80), default="")
    crop_stage: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FarmHistorySnapshot(Base):
    __tablename__ = "farm_history_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    max_pred_temp: Mapped[float] = mapped_column(Float)
    avg_humidity: Mapped[float] = mapped_column(Float)
    max_precip: Mapped[float] = mapped_column(Float)
    ndvi: Mapped[float] = mapped_column(Float)
    soil_moisture: Mapped[float] = mapped_column(Float)
    surface_temp: Mapped[float] = mapped_column(Float)
    alert_count: Mapped[int] = mapped_column(default=0)


class FarmAlertRule(Base):
    __tablename__ = "farm_alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), unique=True, index=True)
    max_temp_threshold: Mapped[float] = mapped_column(Float, default=38.0)
    min_ndvi_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    min_soil_moisture_threshold: Mapped[float] = mapped_column(Float, default=0.20)
    max_wind_threshold: Mapped[float] = mapped_column(Float, default=28.0)
    max_precip_threshold: Mapped[float] = mapped_column(Float, default=75.0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FarmNotificationChannel(Base):
    __tablename__ = "farm_notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), unique=True, index=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_number: Mapped[str] = mapped_column(String(32), default="")
    sms_number: Mapped[str] = mapped_column(String(32), default="")
    email_address: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


def create_db_and_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, name: str, username: str, password: str, role: str = "farmer") -> User:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(name=name, username=username, password_hash=password_hash, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def verify_user_password(user: User, password: str) -> bool:
    return bcrypt.checkpw(password.encode(), user.password_hash.encode())


def list_farms_for_user(db: Session, user_id: int) -> list[Farm]:
    return db.query(Farm).filter(Farm.user_id == user_id).order_by(Farm.created_at.desc()).all()


def create_farm(
    db: Session,
    user_id: int,
    name: str,
    crop_type: str,
    farm_size_acres: float,
    lat: float,
    lon: float,
) -> Farm:
    farm = Farm(
        user_id=user_id,
        name=name,
        crop_type=crop_type,
        farm_size_acres=farm_size_acres,
        lat=lat,
        lon=lon,
    )
    db.add(farm)
    db.commit()
    db.refresh(farm)
    return farm


def get_farm_by_id(db: Session, farm_id: int) -> Farm | None:
    return db.query(Farm).filter(Farm.id == farm_id).first()


def delete_farm(db: Session, farm: Farm) -> None:
    db.query(FarmPlot).filter(FarmPlot.farm_id == farm.id).delete(synchronize_session=False)
    db.delete(farm)
    db.commit()


def create_farm_plot(
    db: Session,
    farm_id: int,
    latitude: float,
    longitude: float,
    plot_name: str,
    soil_type: str = "",
    crop_stage: str = "",
) -> FarmPlot:
    plot = FarmPlot(
        farm_id=farm_id,
        latitude=latitude,
        longitude=longitude,
        plot_name=plot_name,
        soil_type=soil_type,
        crop_stage=crop_stage,
    )
    db.add(plot)
    db.commit()
    db.refresh(plot)
    return plot


def list_plots_for_farm(db: Session, farm_id: int) -> list[FarmPlot]:
    return (
        db.query(FarmPlot)
        .filter(FarmPlot.farm_id == farm_id)
        .order_by(FarmPlot.created_at.desc())
        .all()
    )


def get_plot_by_id(db: Session, plot_id: int) -> FarmPlot | None:
    return db.query(FarmPlot).filter(FarmPlot.id == plot_id).first()


def delete_plot(db: Session, plot: FarmPlot) -> None:
    db.delete(plot)
    db.commit()


def create_history_snapshot(
    db: Session,
    farm_id: int,
    max_pred_temp: float,
    avg_humidity: float,
    max_precip: float,
    ndvi: float,
    soil_moisture: float,
    surface_temp: float,
    alert_count: int,
) -> FarmHistorySnapshot:
    snapshot = FarmHistorySnapshot(
        farm_id=farm_id,
        max_pred_temp=max_pred_temp,
        avg_humidity=avg_humidity,
        max_precip=max_precip,
        ndvi=ndvi,
        soil_moisture=soil_moisture,
        surface_temp=surface_temp,
        alert_count=alert_count,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_history_for_farm(db: Session, farm_id: int, limit: int = 60) -> list[FarmHistorySnapshot]:
    return (
        db.query(FarmHistorySnapshot)
        .filter(FarmHistorySnapshot.farm_id == farm_id)
        .order_by(FarmHistorySnapshot.captured_at.desc())
        .limit(limit)
        .all()
    )


def get_or_create_alert_rule(db: Session, farm_id: int) -> FarmAlertRule:
    rule = db.query(FarmAlertRule).filter(FarmAlertRule.farm_id == farm_id).first()
    if rule:
        return rule

    rule = FarmAlertRule(farm_id=farm_id)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def get_or_create_notification_channel(db: Session, farm_id: int) -> FarmNotificationChannel:
    channel = db.query(FarmNotificationChannel).filter(FarmNotificationChannel.farm_id == farm_id).first()
    if channel:
        return channel

    channel = FarmNotificationChannel(farm_id=farm_id)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def create_notification_delivery_log(
    db: Session,
    farm_id: int,
    channel: str,
    status: str,
    detail: str,
) -> NotificationDeliveryLog:
    row = NotificationDeliveryLog(
        farm_id=farm_id,
        channel=channel,
        status=status,
        detail=(detail or "")[:500],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_notification_delivery_logs(db: Session, farm_id: int, limit: int = 50) -> list[NotificationDeliveryLog]:
    return (
        db.query(NotificationDeliveryLog)
        .filter(NotificationDeliveryLog.farm_id == farm_id)
        .order_by(NotificationDeliveryLog.created_at.desc())
        .limit(limit)
        .all()
    )

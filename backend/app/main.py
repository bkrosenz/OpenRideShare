from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
import logging
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, engine
from .dispatch import complete_ride, create_ride, set_driver_availability
from .models import Invitation, Ride, User
from .routing import OSMRouter, WazeTraffic
from .security import create_token, hash_invitation, hash_password, new_invitation_code, verify_password, verify_token

app = FastAPI(title="OpenRideShare API", version="0.1.0")
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
router = OSMRouter(settings.osrm_url)
traffic = WazeTraffic(settings.waze_feed_url, settings.waze_feed_token)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def get_db():
    with SessionLocal() as session:
        yield session


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_db),
) -> User:
    user_id = verify_token(credentials.credentials, settings.jwt_secret) if credentials and settings.jwt_secret else None
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired credentials")
    return user


class InvitationRequest(BaseModel):
    expires_in_hours: int = Field(default=168, ge=1, le=720)


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: SecretStr
    invitation_code: str = Field(min_length=32, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr


class AvailabilityRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    available: bool


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RideRequest(BaseModel):
    pickup: Coordinate
    dropoff: Coordinate
    tip_cents: int = Field(default=0, ge=0, le=100_000)
    opted_in_providers: list[str] = Field(default_factory=list, max_length=2)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def readiness():
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return {"status": "ready"}


@app.post("/admin/invitations", status_code=201)
def issue_invitation(
    request: InvitationRequest,
    x_admin_key: str | None = Header(default=None),
    session: Session = Depends(get_db),
):
    if not settings.admin_key or not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")
    code = new_invitation_code()
    session.add(Invitation(
        code_hash=hash_invitation(code),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=request.expires_in_hours),
    ))
    session.commit()
    return {"invitation_code": code, "expires_in_hours": request.expires_in_hours}


@app.post("/auth/register", status_code=201)
def register(request: RegistrationRequest, session: Session = Depends(get_db)):
    invitation_hash = hash_invitation(request.invitation_code)
    invitation = session.scalar(select(Invitation).where(Invitation.code_hash == invitation_hash))
    now = datetime.now(timezone.utc)
    expiry = invitation.expires_at.replace(tzinfo=timezone.utc) if invitation and invitation.expires_at.tzinfo is None else invitation.expires_at if invitation else None
    if invitation is None or invitation.used_by is not None or expiry <= now:
        raise HTTPException(status_code=400, detail="Invitation is invalid, expired, or already used")
    if session.scalar(select(User.id).where(User.username == request.username)):
        raise HTTPException(status_code=409, detail="Username is unavailable")
    try:
        password_hash = hash_password(request.password.get_secret_value())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    user = User(id=str(uuid.uuid4()), username=request.username, password_hash=password_hash)
    session.add(user)
    session.flush()
    consumed = session.execute(
        update(Invitation)
        .where(Invitation.code_hash == invitation_hash, Invitation.used_by.is_(None), Invitation.expires_at > now)
        .values(used_by=user.id)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=400, detail="Invitation is invalid, expired, or already used")
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Username is unavailable") from error
    return {"user_id": user.id, "username": user.username}


@app.post("/auth/login")
def login(request: LoginRequest, session: Session = Depends(get_db)):
    user = session.scalar(select(User).where(User.username == request.username))
    if user is None or not verify_password(request.password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    try:
        token = create_token(user.id, settings.jwt_secret, settings.token_minutes * 60)
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Authentication is not configured") from error
    return {"access_token": token, "token_type": "bearer", "expires_in": settings.token_minutes * 60}


@app.get("/auth/me")
def current_user_profile(user: User = Depends(get_current_user)):
    return {"user_id": user.id, "username": user.username}


@app.put("/drivers/availability", status_code=204)
def update_availability(request: AvailabilityRequest, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    set_driver_availability(session, user.id, request.latitude, request.longitude, request.available)


@app.get("/drivers/assigned-rides")
def assigned_rides(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    rides = session.scalars(select(Ride).where(Ride.driver_id == user.id, Ride.status == "matched")).all()
    return [{"ride_id": ride.id, "pickup": [ride.pickup_latitude, ride.pickup_longitude], "dropoff": [ride.dropoff_latitude, ride.dropoff_longitude], "fare_cents": ride.fare_cents, "tip_cents": ride.tip_cents} for ride in rides]


@app.post("/rides", status_code=201)
def request_ride(
    request: RideRequest,
    idempotency_key: str = Header(min_length=16, max_length=128),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    try:
        return create_ride(
            session,
            router,
            traffic,
            settings,
            user.id,
            idempotency_key,
            (request.pickup.latitude, request.pickup.longitude),
            (request.dropoff.latitude, request.dropoff.longitude),
            request.tip_cents,
            request.opted_in_providers,
        )
    except Exception:
        session.rollback()
        logger.exception("Ride dispatch failed")
        raise HTTPException(status_code=503, detail="Ride routing or dispatch is temporarily unavailable")


@app.post("/rides/{ride_id}/complete")
def finish_ride(ride_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    if not complete_ride(session, ride_id, user.id):
        raise HTTPException(status_code=404, detail="Ride not found or cannot be completed")
    return {"status": "completed"}
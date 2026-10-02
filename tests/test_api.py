from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import main
from backend.app.models import Base, Driver, User
from backend.app.routing import Route


@pytest.fixture
def api_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


class FakeRouter:
    def route(self, start, end):
        return Route(5, 20, [[start[0], start[1]], [end[0], end[1]]])


class FakeTraffic:
    def incidents(self):
        return []


def test_auth_invitation_and_ride_endpoints(api_session, monkeypatch):
    configuration = SimpleNamespace(
        admin_key="admin-secret",
        jwt_secret="s" * 48,
        token_minutes=30,
        local_wage_cents_per_hour=2_500,
        users_per_pod=10,
        pod_monthly_cost_cents=5_000,
        rides_per_user_month=4,
        venmo_username="community-driver",
    )
    monkeypatch.setattr(main, "settings", configuration)
    monkeypatch.setattr(main, "router", FakeRouter())
    monkeypatch.setattr(main, "traffic", FakeTraffic())
    assert main.health() == {"status": "ok"}
    assert main.readiness() == {"status": "ready"}

    with pytest.raises(HTTPException) as forbidden:
        main.issue_invitation(main.InvitationRequest(), "wrong", api_session)
    assert forbidden.value.status_code == 403
    invitation = main.issue_invitation(main.InvitationRequest(), "admin-secret", api_session)
    account = main.register(main.RegistrationRequest(username="rider", password="long-test-password", invitation_code=invitation["invitation_code"]), api_session)
    rider = api_session.get(User, account["user_id"])
    assert main.current_user_profile(rider)["username"] == "rider"

    with pytest.raises(HTTPException) as used_invite:
        main.register(main.RegistrationRequest(username="second", password="long-test-password", invitation_code=invitation["invitation_code"]), api_session)
    assert used_invite.value.status_code == 400
    with pytest.raises(HTTPException) as bad_login:
        main.login(main.LoginRequest(username="rider", password="wrong-password"), api_session)
    assert bad_login.value.status_code == 401
    token_result = main.login(main.LoginRequest(username="rider", password="long-test-password"), api_session)
    credentials = main.HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_result["access_token"])
    assert main.get_current_user(credentials, api_session).id == rider.id
    with pytest.raises(HTTPException):
        main.get_current_user(None, api_session)

    driver = User(id="driver-id", username="driver", password_hash=b"hash")
    api_session.add(driver)
    api_session.commit()
    main.update_availability(main.AvailabilityRequest(latitude=0, longitude=0, available=True), driver, api_session)
    assert api_session.get(Driver, driver.id).available is True
    assert main.assigned_rides(driver, api_session) == []

    ride_request = main.RideRequest(
        pickup=main.Coordinate(latitude=1, longitude=1),
        dropoff=main.Coordinate(latitude=2, longitude=2),
        tip_cents=100,
    )
    result = main.request_ride(ride_request, "request-key-0000001", rider, api_session)
    assert result["driver_id"] == driver.id
    assert len(main.assigned_rides(driver, api_session)) == 1
    assert main.finish_ride(result["ride_id"], driver, api_session) == {"status": "completed"}
    assert api_session.get(Driver, driver.id).available is True
    with pytest.raises(HTTPException) as missing_ride:
        main.finish_ride("not-a-ride", rider, api_session)
    assert missing_ride.value.status_code == 404
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.dispatch import complete_ride, create_ride, rideshare_handoff_links, set_driver_availability, venmo_payment_uri
from backend.app.domain import calculate_fare, estimate_pod_count
from backend.app.models import Base, Driver, Ride, User
from backend.app.routing import OSMRouter, Route, WazeTraffic, haversine_miles, traffic_delay_minutes
from backend.app.security import create_token, hash_invitation, hash_password, new_invitation_code, verify_password, verify_token


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        yield value
    engine.dispose()


def test_pod_estimate_and_fare_components():
    assert estimate_pod_count(0, 10) == 1
    assert estimate_pod_count(11, 10) == 2
    with pytest.raises(ValueError):
        estimate_pod_count(2, 0)
    fare = calculate_fare(10, 30, 2_500, 1_000, 500, 50_000, 4_000)
    assert fare.pod_count == 2
    assert fare.mileage_component_cents == 760
    assert fare.labor_component_cents == 1_250
    assert fare.hosting_component_cents == 25
    assert fare.fare_cents == 1_275
    assert calculate_fare(20, 1, 0, 0, 10, 100, 1).fare_cents == 1_520
    with pytest.raises(ValueError):
        calculate_fare(-1, 0, 0, 0, 10, 0, 1)


def test_password_and_token_helpers():
    hashed = hash_password("a-very-long-example-password")
    assert verify_password("a-very-long-example-password", hashed)
    assert not verify_password("different-password", hashed)
    assert not verify_password("bad", b"not-a-hash")
    with pytest.raises(ValueError):
        hash_password("short")
    with pytest.raises(ValueError):
        create_token("user", "weak", 60)
    token = create_token("user-id", "x" * 40, 60)
    assert verify_token(token, "x" * 40) == "user-id"
    assert verify_token(token + "x", "x" * 40) is None
    assert verify_token("malformed", "x" * 40) is None
    invitation = new_invitation_code()
    assert len(invitation) >= 32
    assert hash_invitation(invitation) != invitation


def test_routing_adapter_and_distance_helpers():
    def handler(request):
        assert request.url.params["alternatives"] == "true"
        return httpx.Response(200, json={"routes": [
            {"distance": 2_000, "duration": 120, "geometry": {"coordinates": [[-71, 42], [-70, 43]]}},
            {"distance": 1_000, "duration": 60, "geometry": {"coordinates": [[-71, 42], [-70, 43]]}},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    route = OSMRouter("https://routing.example", client).route((42, -71), (43, -70))
    assert route.distance_miles == pytest.approx(1_000 / 1609.344)
    assert route.duration_minutes == 1
    assert route.geometry == [[42, -71], [43, -70]]
    assert haversine_miles((0, 0), (0, 1)) == pytest.approx(69.1, abs=0.2)

    no_route = OSMRouter("https://routing.example", httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"routes": []}))))
    with pytest.raises(ValueError):
        no_route.route((0, 0), (1, 1))


def test_waze_adapter_and_incident_delay():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (
        httpx.Response(200, json={"alerts": [{"location": {"y": 42, "x": -71}, "delay": 120}], "jams": []})
        if request.headers.get("Authorization") == "Bearer secret"
        else httpx.Response(401)
    )))
    incidents = WazeTraffic("https://feed.example", "secret", client).incidents()
    route = Route(5, 10, [[42, -71], [42.1, -71.1]])
    assert len(incidents) == 1
    assert traffic_delay_minutes(route, incidents) == 2
    assert WazeTraffic("", "").incidents() == []
    assert traffic_delay_minutes(route, [{"location": {}, "delay": 60}]) == 0


def test_payment_and_opt_in_provider_links():
    uri = venmo_payment_uri("community-driver", "ride id", 900, 125)
    assert uri is not None
    params = parse_qs(urlparse(uri).query)
    assert params["amount"] == ["10.25"]
    assert venmo_payment_uri("", "ride", 100, 0) is None
    links = rideshare_handoff_links(["uber", "lyft", "other"], (1, 2), (3, 4))
    assert set(links) == {"uber", "lyft"}
    assert rideshare_handoff_links([], (1, 2), (3, 4)) == {}


class FakeRouter:
    def route(self, start, end):
        miles = max(0.1, (abs(start[0] - end[0]) + abs(start[1] - end[1])) * 10)
        return Route(miles, 30, [[start[0], start[1]], [end[0], end[1]]])


class FakeTraffic:
    def incidents(self):
        return []


def seed_user(session, user_id, driver=False, latitude=0.0):
    session.add(User(id=user_id, username=user_id, password_hash=b"hash"))
    if driver:
        session.add(Driver(user_id=user_id, latitude=latitude, longitude=0, available=True))
    session.commit()


def test_dispatch_orders_by_driving_distance_and_claims_once(session):
    seed_user(session, "rider")
    seed_user(session, "far", driver=True, latitude=0.8)
    seed_user(session, "near", driver=True, latitude=0.9)
    config = SimpleNamespace(local_wage_cents_per_hour=2_500, users_per_pod=10, pod_monthly_cost_cents=5_000, rides_per_user_month=4, venmo_username="driver")

    result = create_ride(session, FakeRouter(), FakeTraffic(), config, "rider", "request-key-00001", (1, 1), (2, 2), 125)
    assert result["status"] == "matched"
    assert result["driver_id"] == "near"
    assert result["tip_cents"] == 125
    assert result["payment_uri"].startswith("venmo://")
    assert result["fare_breakdown"]["estimated_eks_pods"] == 1
    assert session.get(Driver, "near").available is False

    repeated = create_ride(session, FakeRouter(), FakeTraffic(), config, "rider", "request-key-00001", (1, 1), (2, 2))
    assert repeated["ride_id"] == result["ride_id"]
    assert session.scalar(select(Ride).where(Ride.rider_id == "rider")).tip_cents == 125

    second = create_ride(session, FakeRouter(), FakeTraffic(), config, "rider", "request-key-00002", (1, 1), (2, 2), opted_in_providers=["uber"])
    assert second["driver_id"] == "far"


def test_unmatched_ride_handoff_and_driver_lifecycle(session):
    seed_user(session, "rider")
    config = SimpleNamespace(local_wage_cents_per_hour=2_500, users_per_pod=10, pod_monthly_cost_cents=5_000, rides_per_user_month=4, venmo_username="")
    result = create_ride(session, FakeRouter(), FakeTraffic(), config, "rider", "request-key-00003", (1, 1), (2, 2), opted_in_providers=["lyft", "unsupported"])
    assert result["status"] == "unmatched"
    assert set(result["handoff_options"]) == {"lyft"}
    assert result["payment_uri"] is None

    set_driver_availability(session, "driver", 0, 0, True)
    assert session.get(Driver, "driver").available is True
    set_driver_availability(session, "driver", 1, 1, False)
    assert session.get(Driver, "driver").latitude == 1
    assert session.get(Driver, "driver").available is False
    assert complete_ride(session, result["ride_id"], "rider") is False


def test_complete_ride_only_by_participant_and_releases_driver(session):
    seed_user(session, "rider")
    seed_user(session, "driver", driver=True)
    ride = Ride(id="ride-1", rider_id="rider", driver_id="driver", idempotency_key="key", pickup_latitude=0, pickup_longitude=0, dropoff_latitude=1, dropoff_longitude=1, distance_miles=1, duration_minutes=1, fare_cents=100, tip_cents=0, status="matched")
    session.add(ride)
    session.commit()
    assert complete_ride(session, "ride-1", "not-a-participant") is False
    assert complete_ride(session, "ride-1", "rider") is True
    assert session.get(Driver, "driver").available is True
    assert complete_ride(session, "ride-1", "rider") is False
    assert complete_ride(session, "missing", "rider") is False
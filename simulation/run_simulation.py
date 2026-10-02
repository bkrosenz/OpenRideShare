from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.dispatch import create_ride
from backend.app.models import Base, Driver, Ride, User
from backend.app.routing import Route


class MockRouter:
    def route(self, start, end):
        miles = max(0.1, (abs(start[0] - end[0]) + abs(start[1] - end[1])) * 10)
        return Route(miles, max(3, miles * 2), [[start[0], start[1]], [end[0], end[1]]])


class MockTraffic:
    def incidents(self):
        return []


def run_simulation(rider_count: int = 100, driver_count: int = 10) -> dict:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(
        local_wage_cents_per_hour=2_500,
        users_per_pod=50,
        pod_monthly_cost_cents=5_000,
        rides_per_user_month=4,
        venmo_username="simulation-driver",
    )
    with Session(engine, expire_on_commit=False) as session:
        for index in range(rider_count):
            session.add(User(id=f"rider-{index}", username=f"mock-rider-{index}", password_hash=b"mock"))
        for index in range(driver_count):
            session.add(User(id=f"driver-{index}", username=f"mock-driver-{index}", password_hash=b"mock"))
            session.add(Driver(user_id=f"driver-{index}", latitude=0.95 + index * 0.01, longitude=0.95, available=True))
        session.commit()

        outcomes = {"matched": 0, "unmatched": 0}
        for index in range(rider_count):
            result = create_ride(
                session,
                MockRouter(),
                MockTraffic(),
                settings,
                f"rider-{index}",
                f"simulation-request-{index:04d}",
                (1.0, 1.0),
                (2.0, 2.0),
                tip_cents=index % 500,
            )
            outcomes[result["status"]] += 1

        rides = session.scalars(select(Ride)).all()
        matched_drivers = [ride.driver_id for ride in rides if ride.driver_id]
        assert len(rides) == rider_count
        assert len(matched_drivers) == len(set(matched_drivers)) == driver_count
        assert outcomes == {"matched": driver_count, "unmatched": rider_count - driver_count}
        assert all(ride.fare_cents >= round(ride.distance_miles * 76) for ride in rides)
        return {"riders": rider_count, "drivers": driver_count, "outcomes": outcomes, "unique_driver_assignments": len(set(matched_drivers))}


if __name__ == "__main__":
    summary = run_simulation()
    print(f"Simulation passed: {summary}")
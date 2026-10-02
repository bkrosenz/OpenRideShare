from __future__ import annotations

from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import Settings
from .domain import calculate_fare
from .models import Driver, Ride, User
from .routing import OSMRouter, WazeTraffic, traffic_delay_minutes


def venmo_payment_uri(username: str, ride_id: str, amount_cents: int, tip_cents: int) -> str | None:
    if not username:
        return None
    amount = f"{(amount_cents + tip_cents) / 100:.2f}"
    query = urlencode({"txn": "pay", "recipients": username, "amount": amount, "note": f"OpenRideShare ride {ride_id}"})
    return f"venmo://paycharge?{query}"


def rideshare_handoff_links(
    providers: list[str], pickup: tuple[float, float], dropoff: tuple[float, float]
) -> dict[str, str]:
    links = {}
    if "uber" in providers:
        query = urlencode({"action": "setPickup", "pickup[latitude]": pickup[0], "pickup[longitude]": pickup[1], "dropoff[latitude]": dropoff[0], "dropoff[longitude]": dropoff[1]})
        links["uber"] = f"https://m.uber.com/ul/?{query}"
    if "lyft" in providers:
        query = urlencode({"id": "lyft", "pickup[latitude]": pickup[0], "pickup[longitude]": pickup[1], "destination[latitude]": dropoff[0], "destination[longitude]": dropoff[1]})
        links["lyft"] = f"lyft://ridetype?{query}"
    return links


def _as_result(ride: Ride, venmo_username: str) -> dict:
    return {
        "ride_id": ride.id,
        "status": ride.status,
        "driver_id": ride.driver_id,
        "distance_miles": ride.distance_miles,
        "duration_minutes": ride.duration_minutes,
        "fare_cents": ride.fare_cents,
        "tip_cents": ride.tip_cents,
        "payment_uri": venmo_payment_uri(venmo_username, ride.id, ride.fare_cents, ride.tip_cents),
    }


def create_ride(
    session: Session,
    router: OSMRouter,
    traffic: WazeTraffic,
    settings: Settings,
    rider_id: str,
    idempotency_key: str,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    tip_cents: int = 0,
    opted_in_providers: list[str] | None = None,
) -> dict:
    previous = session.scalar(select(Ride).where(Ride.rider_id == rider_id, Ride.idempotency_key == idempotency_key))
    if previous:
        result = _as_result(previous, settings.venmo_username)
        result["handoff_options"] = {}
        return result

    ride_route = router.route(pickup, dropoff)
    incidents = traffic.incidents()
    duration = ride_route.duration_minutes + traffic_delay_minutes(ride_route, incidents)
    active_users = session.scalar(select(func.count(User.id))) or 0
    fare = calculate_fare(
        ride_route.distance_miles,
        duration,
        settings.local_wage_cents_per_hour,
        active_users,
        settings.users_per_pod,
        settings.pod_monthly_cost_cents,
        max(1, active_users * settings.rides_per_user_month),
    )

    candidates = session.scalars(select(Driver).where(Driver.available.is_(True))).all()
    by_distance = []
    for candidate in candidates:
        try:
            approach = router.route((candidate.latitude, candidate.longitude), pickup)
        except (ValueError, OSError):
            continue
        by_distance.append((approach.distance_miles, candidate.user_id))
    by_distance.sort()

    ride_id = str(uuid4())
    selected_driver = None
    for _, candidate_id in by_distance:
        claimed = session.execute(
            update(Driver)
            .where(Driver.user_id == candidate_id, Driver.available.is_(True))
            .values(available=False)
        )
        if claimed.rowcount == 1:
            selected_driver = candidate_id
            break

    ride = Ride(
        id=ride_id,
        rider_id=rider_id,
        driver_id=selected_driver,
        idempotency_key=idempotency_key,
        pickup_latitude=pickup[0],
        pickup_longitude=pickup[1],
        dropoff_latitude=dropoff[0],
        dropoff_longitude=dropoff[1],
        distance_miles=ride_route.distance_miles,
        duration_minutes=duration,
        fare_cents=fare.fare_cents,
        tip_cents=tip_cents,
        status="matched" if selected_driver else "unmatched",
    )
    session.add(ride)
    session.commit()
    result = _as_result(ride, settings.venmo_username)
    requested = [provider for provider in (opted_in_providers or []) if provider in {"uber", "lyft"}]
    result["handoff_options"] = rideshare_handoff_links(requested, pickup, dropoff) if not selected_driver else {}
    result["fare_breakdown"] = {
        "mileage_floor_cents": fare.mileage_component_cents,
        "labor_cents": fare.labor_component_cents,
        "allocated_hosting_cents": fare.hosting_component_cents,
        "estimated_eks_pods": fare.pod_count,
    }
    return result


def set_driver_availability(session: Session, user_id: str, latitude: float, longitude: float, available: bool) -> None:
    driver = session.get(Driver, user_id)
    if driver is None:
        driver = Driver(user_id=user_id, latitude=latitude, longitude=longitude, available=available)
        session.add(driver)
    else:
        driver.latitude, driver.longitude, driver.available = latitude, longitude, available
    session.commit()


def complete_ride(session: Session, ride_id: str, user_id: str) -> bool:
    ride = session.scalar(select(Ride).where(Ride.id == ride_id))
    if ride is None or user_id not in {ride.rider_id, ride.driver_id} or ride.status != "matched":
        return False
    ride.status = "completed"
    if ride.driver_id:
        session.execute(update(Driver).where(Driver.user_id == ride.driver_id).values(available=True))
    session.commit()
    return True
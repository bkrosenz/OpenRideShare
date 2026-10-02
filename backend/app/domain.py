from __future__ import annotations

from dataclasses import dataclass
from math import ceil

MILEAGE_RATE_CENTS = 76


@dataclass(frozen=True)
class Fare:
    fare_cents: int
    mileage_component_cents: int
    labor_component_cents: int
    hosting_component_cents: int
    pod_count: int


def estimate_pod_count(user_count: int, users_per_pod: int) -> int:
    if user_count < 0 or users_per_pod < 1:
        raise ValueError("user_count must be nonnegative and users_per_pod positive")
    return max(1, ceil(user_count / users_per_pod))


def calculate_fare(
    distance_miles: float,
    duration_minutes: float,
    local_living_wage_cents_per_hour: int,
    active_users: int,
    users_per_pod: int,
    pod_monthly_cost_cents: int,
    projected_monthly_rides: int,
) -> Fare:
    """Price a ride as max(mileage floor, labor + allocated EKS estimate)."""
    if distance_miles < 0 or duration_minutes < 0:
        raise ValueError("distance and duration must be nonnegative")
    if local_living_wage_cents_per_hour < 0 or pod_monthly_cost_cents < 0:
        raise ValueError("wage and hosting costs must be nonnegative")
    if projected_monthly_rides < 1:
        raise ValueError("projected_monthly_rides must be positive")

    pods = estimate_pod_count(active_users, users_per_pod)
    mileage = round(distance_miles * MILEAGE_RATE_CENTS)
    labor = round(duration_minutes / 60 * local_living_wage_cents_per_hour)
    hosting = ceil(pods * pod_monthly_cost_cents / projected_monthly_rides)
    return Fare(max(mileage, labor + hosting), mileage, labor, hosting, pods)
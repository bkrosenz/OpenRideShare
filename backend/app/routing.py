from __future__ import annotations

from dataclasses import dataclass
import math

import httpx


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_minutes: float
    geometry: list[list[float]]


def haversine_miles(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*start, *end))
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 3958.7613 * 2 * math.asin(math.sqrt(value))


class OSMRouter:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=8.0)

    def route(self, start: tuple[float, float], end: tuple[float, float]) -> Route:
        coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
        response = self.client.get(
            f"{self.base_url}/route/v1/driving/{coordinates}",
            params={"overview": "full", "geometries": "geojson", "alternatives": "true", "steps": "false"},
        )
        response.raise_for_status()
        routes = response.json().get("routes", [])
        if not routes:
            raise ValueError("No drivable route found")
        shortest = min(routes, key=lambda route: route["distance"])
        coordinates = shortest.get("geometry", {}).get("coordinates", [])
        return Route(
            distance_miles=shortest["distance"] / 1609.344,
            duration_minutes=shortest["duration"] / 60,
            geometry=[[lat, lon] for lon, lat in coordinates],
        )


class WazeTraffic:
    """Reads an authorized Waze for Cities feed; no scraping or consumer-app API use."""

    def __init__(self, feed_url: str, token: str, client: httpx.Client | None = None):
        self.feed_url, self.token = feed_url, token
        self.client = client or httpx.Client(timeout=5.0)

    def incidents(self) -> list[dict]:
        if not self.feed_url or not self.token:
            return []
        response = self.client.get(self.feed_url, headers={"Authorization": f"Bearer {self.token}"})
        response.raise_for_status()
        payload = response.json()
        return payload.get("alerts", []) + payload.get("jams", [])


def traffic_delay_minutes(route: Route, incidents: list[dict]) -> float:
    """Conservative ETA adjustment for active feed incidents near route vertices."""
    delay = 0.0
    for incident in incidents:
        location = incident.get("location", {})
        latitude, longitude = location.get("y"), location.get("x")
        if latitude is None or longitude is None:
            continue
        if any(haversine_miles((latitude, longitude), tuple(point)) <= 0.2 for point in route.geometry):
            delay += max(0.0, float(incident.get("delay", 0)) / 60)
    return delay
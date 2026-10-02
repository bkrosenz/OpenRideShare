from __future__ import annotations

import os
import secrets

import requests


class RideShareAPI:
    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or os.getenv("OPENRIDESHARE_API", "https://api.openrideshare.example")).rstrip("/")
        self.session = session or requests.Session()
        self.token: str | None = None

    def _request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.session.request(method, f"{self.base_url}{path}", headers=headers, timeout=12, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def register(self, username: str, password: str, invitation_code: str) -> dict:
        return self._request("POST", "/auth/register", json={"username": username, "password": password, "invitation_code": invitation_code})

    def login(self, username: str, password: str) -> dict:
        result = self._request("POST", "/auth/login", json={"username": username, "password": password})
        self.token = result["access_token"]
        return result

    def request_ride(self, pickup: tuple[float, float], dropoff: tuple[float, float], tip_cents: int, providers: list[str]) -> dict:
        return self._request(
            "POST",
            "/rides",
            headers={"Idempotency-Key": secrets.token_urlsafe(24)},
            json={
                "pickup": {"latitude": pickup[0], "longitude": pickup[1]},
                "dropoff": {"latitude": dropoff[0], "longitude": dropoff[1]},
                "tip_cents": tip_cents,
                "opted_in_providers": providers,
            },
        )

    def update_driver(self, latitude: float, longitude: float, available: bool) -> None:
        self._request("PUT", "/drivers/availability", json={"latitude": latitude, "longitude": longitude, "available": available})

    def assigned_rides(self) -> list[dict]:
        return self._request("GET", "/drivers/assigned-rides")


def open_android_uri(uri: str, package_name: str) -> bool:
    """Open only a user-selected payment or rideshare URI on Android."""
    try:
        from jnius import autoclass

        activity_class = autoclass("org.kivy.android.PythonActivity")
        intent_class = autoclass("android.content.Intent")
        uri_class = autoclass("android.net.Uri")
        activity = activity_class.mActivity
        intent = intent_class(intent_class.ACTION_VIEW, uri_class.parse(uri))
        intent.setPackage(package_name)
        if intent.resolveActivity(activity.getPackageManager()) is None:
            return False
        activity.startActivity(intent)
        return True
    except (ImportError, RuntimeError):
        return False
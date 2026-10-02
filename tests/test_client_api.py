from client.api import RideShareAPI, open_android_uri


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.content = b"present"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/auth/login"):
            return FakeResponse({"access_token": "session-token"})
        if url.endswith("/drivers/assigned-rides"):
            return FakeResponse([])
        if url.endswith("/drivers/availability"):
            return FakeResponse({})
        return FakeResponse({"status": "matched"})


def test_client_api_methods_and_android_handoff():
    session = FakeSession()
    api = RideShareAPI("https://api.example", session)
    assert api.register("rider", "long-password", "invitation") == {"status": "matched"}
    assert api.login("rider", "long-password")["access_token"] == "session-token"
    ride = api.request_ride((1, 2), (3, 4), 125, ["lyft"])
    assert ride["status"] == "matched"
    api.update_driver(1, 2, True)
    assert api.assigned_rides() == []
    assert all(call[2]["headers"]["Authorization"] == "Bearer session-token" for call in session.calls[2:])
    assert session.calls[2][2]["headers"]["Idempotency-Key"]
    assert open_android_uri("venmo://paycharge?amount=1.00", "com.venmo") is False